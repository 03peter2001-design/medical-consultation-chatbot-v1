"""Patient questionnaire and AMIE interview endpoints."""

import asyncio
import time
from copy import deepcopy
from weakref import WeakValueDictionary

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
)

from amie import (
    AMIEEngine,
    ChiefComplaintExtractor,
    build_fhir_risk_profile,
    detect_red_flags,
    detect_structured_red_flags,
    preferred_route,
    prioritized_routes,
)
from amie.clinical_facts import (
    facts_from_assessment,
    filter_question_by_known_facts,
    merge_facts,
)
from amie.disease_profiles import attach_safety_conditions
from amie.models import ChiefComplaintAssessment
from app.contracts import PatientChatResponse, error_responses
from app.models import ChatRequest, PatientPrefill
from app.runtime import (
    AMIE_DEBUG_TRACE,
    INTERVIEW_ENGINE,
    SESSION_TTL,
    URGENT_CARE_MESSAGE,
    consultation_repository,
    get_gemini_summary_client,
    llm_client,
    sessions,
)
from app.security import current_patient_session, require_patient_session
from app.services.amie_audit import (
    append_amie_trace as _append_amie_trace,
)
from app.services.amie_audit import (
    append_manual_amie_trace as _append_manual_amie_trace,
)
from app.services.amie_audit import (
    save_amie_state as _save_amie_state,
)
from app.services.async_clinical_io import (
    ClinicalOperationTimeout,
    run_clinical_io,
)
from app.services.clinical_summary import (
    build_structured_emr,
    build_summary,
    clinical_patient_data,
)
from app.services.consultation_reporting import (
    process_background_summaries,
)
from app.services.gemini_questionnaire_summary import (
    PROMPT_VERSION as GEMINI_SUMMARY_PROMPT_VERSION,
)
from app.services.gemini_questionnaire_summary import (
    build_summary_messages,
    questionnaire_answers,
)
from app.services.gemini_questionnaire_summary import (
    parse_summary as parse_gemini_summary,
)
from app.services.gemini_questionnaire_summary import (
    render_emr as render_gemini_emr,
)
from app.services.input_validation import (
    store_question_answer,
    validate_question_answer,
)
from app.services.patient_interview import (
    ROUTE_KEYWORDS,
    SUPPORTED_PATIENT_ROUTES,
    local_complaint_route,
    route_keyword_hits,
)
from app.services.patient_interview import (
    URGENT_CONDITION_CANDIDATES as URGENT_CONDITION_CANDIDATES,
)
from app.services.patient_interview import (
    amie_initial_session as _amie_initial_session,
)
from app.services.patient_interview import (
    apply_chief_questionnaire_prefills as _apply_chief_questionnaire_prefills,
)
from app.services.patient_interview import (
    complaint_routes as _complaint_routes,
)
from app.services.patient_interview import (
    copy_prefills_to_secondary_routes as _copy_prefills_to_secondary_routes,
)
from app.services.patient_interview import (
    prefilled_patient_data as _prefilled_patient_data,
)
from app.services.patient_interview import (
    section_transition_reply as _section_transition_reply,
)
from app.services.patient_interview import (
    urgent_possible_conditions as _urgent_possible_conditions,
)
from app.services.rag import deduplicate_sources, retrieve_context_block
from app.services.security_audit import audit_patient, safe_log
from domain.patient_messages import patient_message
from domain.questionnaires import (
    BASIC_QUESTIONNAIRE,
    CHIEF_QUESTIONNAIRE,
    HISTORY_QUESTIONNAIRE,
    ROUTE_LABELS,
    build_questionnaire,
    condition_matches,
    filter_question_by_context,
    next_question_index,
    progress_meta,
    questionnaire_disposition,
    questionnaire_meta,
)
from domain.questionnaires import (
    question_input as structured_question_input,
)

router = APIRouter(tags=["patient"])
_patient_chat_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

_HISTORY_LIMIT = 16


def _cleanup_sessions():
    now = time.time()
    expired = [sid for sid, s in sessions.items() if now - s.get("ts", 0) > SESSION_TTL]
    for sid in expired:
        del sessions[sid]


def _record_question_history(session: dict) -> None:
    """Save the pre-answer state so the patient can revisit the question."""
    snapshot = deepcopy(
        {
            key: value
            for key, value in session.items()
            if key not in {"_history", "_integration", "transcript", "ts"}
        }
    )
    snapshot["_transcript_length"] = len(session.get("transcript", []))
    history = session.setdefault("_history", [])
    history.append(snapshot)
    if len(history) > _HISTORY_LIMIT:
        del history[:-_HISTORY_LIMIT]


def _restore_previous_question(session: dict) -> dict:
    history = session.get("_history", [])
    if session.get("index") == -1 or not history:
        return _question_payload(
            session,
            reply=patient_message("navigation.no_previous_question"),
            completed=session.get("index") == -1,
        )

    snapshot = history.pop()
    integration = session.get("_integration")
    transcript = session.get("transcript", [])[: snapshot.pop("_transcript_length", 0)]
    session.clear()
    session.update(snapshot)
    session["_history"] = history
    if session.get("engine") == "amie":
        session["transcript"] = transcript
    session["ts"] = time.time()
    if integration is not None:
        session["_integration"] = integration

    questionnaire = session.get("questionnaire", CHIEF_QUESTIONNAIRE)
    index = session.get("index", 0)
    current = questionnaire[index]
    return _question_payload(
        session,
        reply=patient_message("navigation.previous_question", prompt=current["prompt"]),
    )


def classify_complaint(text: str) -> str:
    """Use deterministic routing first; ask the LLM only when ambiguous."""
    hits = route_keyword_hits(text)
    matched = [k for k, v in hits.items() if v]
    local_route = local_complaint_route(text)
    if local_route:
        return local_route

    try:
        result = llm_client.generate_text(
            [
                {
                    "role": "system",
                    "content": (
                        "你是急診分流護理師。請判斷病患描述的主訴最符合以下哪一類："
                        + "、".join(
                            f"{route}（{ROUTE_LABELS[route]}相關不適）" for route in ROUTE_KEYWORDS
                        )
                        + "、other（以上皆非）。只能回傳一個英文代碼："
                        + "、".join([*ROUTE_KEYWORDS, "other"])
                        + "，不要有其他文字。"
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0,
            max_tokens=32,
        )
        route = result.strip().lower().strip("`'\".。 ")
        if route in {*ROUTE_KEYWORDS, "other"}:
            return route
        raise ValueError(f"無效的分流輸出：{route[:20]}")
    except Exception as e:
        safe_log("patient.classify", "failure", error=e)
        if matched:
            return matched[0]
        return "other"


def _question_payload(
    session: dict,
    *,
    reply: str,
    user_display=None,
    completed: bool = False,
    queue_number: str | None = None,
) -> dict:
    questionnaire = session.get("questionnaire", CHIEF_QUESTIONNAIRE)
    index = session.get("index", 0)
    data = session.get("data", {})
    current = questionnaire[index] if not completed and 0 <= index < len(questionnaire) else None
    if current is not None:
        current = filter_question_by_context(current, data)
        if isinstance(questionnaire, list):
            questionnaire[index] = current
    if session.get("engine") == "amie":
        active = [item for item in questionnaire if condition_matches(item, data)]
        completed_fields = set(data) | set(session.get("prefilled_fields", []))
        answered = sum(item["field"] in completed_fields for item in active)
        total = max(len(active), 1)
        amie_progress = {
            "current": min(total, answered + (0 if completed else 1)),
            "total": total,
            "percent": (100 if completed else min(99, round((answered / total) * 100))),
        }
    else:
        amie_progress = None

    debug_event = None
    if AMIE_DEBUG_TRACE and session.get("engine") == "amie" and session.get("transcript"):
        event = session["transcript"][-1]
        decision = event.get("decision") or {}
        candidate_frontier = decision.get("candidate_frontier") or []
        funnel = (
            {
                "selection_phase": decision.get("selection_phase", ""),
                "selection_tier": decision.get("selection_tier", ""),
                "candidate_count": len(candidate_frontier),
                "target_fact_codes": list(decision.get("target_fact_codes") or []),
                "funnel_score": dict(decision.get("funnel_score") or {}),
            }
            if decision.get("selection_phase")
            else None
        )
        blocked = {
            "candidate_frontier",
            "disease_assessment",
            "disease_votes",
            "differential_hypotheses",
            "funnel_score",
            "selection_phase",
            "selection_tier",
            "target_fact_codes",
        }
        debug_event = {
            "turn": event.get("turn"),
            "question": event.get("question"),
            "answer": event.get("answer"),
            "decision": {key: value for key, value in decision.items() if key not in blocked},
            "funnel": funnel,
            "result": {
                key: value
                for key, value in (event.get("result") or {}).items()
                if key not in blocked
            },
            "reason": event.get("reason", ""),
            "model_error": event.get("model_error", ""),
        }

    triage = {
        "level": session.get("triage_level", "routine"),
        "message": (URGENT_CARE_MESSAGE if session.get("triage_level") == "urgent" else ""),
    }
    if triage["level"] == "urgent":
        triage["possible_conditions"] = _urgent_possible_conditions(session)

    return {
        "reply": reply,
        "session_id": session["session_id"],
        "completed": completed,
        "can_go_back": bool(session.get("_history")) and not completed,
        "user_display": user_display,
        "step": -1 if completed else index,
        "queue_number": queue_number,
        "triage": triage,
        "question_input": (structured_question_input(current) if current else None),
        "questionnaire": (questionnaire_meta(current, data.get("type")) if current else None),
        "progress": (
            {"current": 1, "total": 1, "percent": 100}
            if completed
            else (amie_progress or progress_meta(questionnaire, index, data))
        ),
        "amie_debug": debug_event,
    }


def _questionnaire_rag_contexts(data: dict) -> tuple[dict[str, str], list[dict]]:
    """Retrieve the three evidence blocks used by the six-part final report."""

    reason = str(data.get("reason") or "").strip()
    route = str(data.get("type") or "")
    primary_route = route if route in SUPPORTED_PATIENT_ROUTES else None
    patient_data = clinical_patient_data(data)
    diagnosis, diagnosis_sources = retrieve_context_block(
        f"{reason} 鑑別診斷 危險徵兆 紅旗症狀",
        n_results=5,
        primary_route=primary_route,
        patient_data=patient_data,
        purpose="diagnosis",
    )
    laboratory, laboratory_sources = retrieve_context_block(
        f"{reason} 抽血檢驗 實驗室檢查",
        n_results=4,
        primary_route=primary_route,
        patient_data=patient_data,
        purpose="lab",
    )
    imaging, imaging_sources = retrieve_context_block(
        f"{reason} 影像學 X光 電腦斷層 CT MRI 超音波",
        n_results=4,
        primary_route=primary_route,
        patient_data=patient_data,
        purpose="imaging",
    )
    return (
        {
            "diagnosis": diagnosis,
            "laboratory": laboratory,
            "imaging": imaging,
        },
        deduplicate_sources(
            diagnosis_sources,
            laboratory_sources,
            imaging_sources,
        ),
    )


async def _complete_questionnaire_consultation(
    session: dict,
    user_display: str,
) -> dict:
    data = session["data"]
    ctype = data["type"]
    answers = questionnaire_answers(session["questionnaire"], data)
    prefilled_data = {
        field: data[field] for field in session.get("prefilled_fields", []) if field in data
    }
    try:
        knowledge_contexts, structured_sources = await run_clinical_io(
            _questionnaire_rag_contexts,
            data,
        )
        client = get_gemini_summary_client()
        raw = await run_clinical_io(
            client.generate_text,
            build_summary_messages(
                answers,
                prefilled_data=prefilled_data,
                knowledge_contexts=knowledge_contexts,
            ),
            temperature=0.2,
            max_tokens=3200,
        )
        generated = parse_gemini_summary(raw)
    except Exception as error:
        safe_log("patient.questionnaire_summary", "failure", error=error)
        raise HTTPException(
            status_code=503,
            detail="Gemini 目前無法整理問診結果，答案已保留，請稍後重試。",
        ) from error
    structured_note = render_gemini_emr(generated, model=client.model)
    data["_questionnaire_answers"] = answers
    data["_gemini_emr"] = generated.emr
    data["_interview_pipeline"].update(
        {
            "model": client.model,
            "prompt_version": GEMINI_SUMMARY_PROMPT_VERSION,
            "postprocess": "single_gemini_six_part_report_after_questionnaire",
            "rag_contexts": ["diagnosis", "laboratory", "imaging"],
        }
    )
    created = consultation_repository.create_with_identifiers(
        {
            "session_id": session["session_id"],
            "type": ctype,
            "reason": data.get("reason", ""),
            "summary": structured_note,
            "report": structured_note,
            "data": data,
            "structured_note": structured_note,
            "structured_sources": structured_sources,
            "triage_level": "routine",
            "status": "completed",
            **session.get("_integration", {}),
        }
    )
    queue_number = created["queue_number"]
    session["step"] = -1
    session["index"] = -1
    reply = patient_message("completion.routine", queue_number=queue_number)
    return _question_payload(
        session,
        reply=reply,
        user_display=user_display,
        completed=True,
        queue_number=queue_number,
    )


async def _complete_consultation(
    session: dict,
    user_display: str,
    background_tasks: BackgroundTasks,
) -> dict:
    data = session["data"]
    ctype = data["type"]
    if data.get("_interview_pipeline", {}).get("engine") == "questionnaire":
        return await _complete_questionnaire_consultation(session, user_display)

    created = consultation_repository.create_with_identifiers(
        {
            "session_id": session["session_id"],
            "type": ctype,
            "reason": data.get("reason", ""),
            "summary": build_summary(data),
            "report": patient_message("report.summary_pending"),
            "data": data,
            "structured_note": None,
            "structured_sources": [],
            "triage_level": "routine",
            "status": "summary_pending",
            **session.get("_integration", {}),
        }
    )
    queue_number = created["queue_number"]
    background_tasks.add_task(
        process_background_summaries,
        created["consultation_id"],
    )
    session["step"] = -1
    session["index"] = -1
    reply = patient_message("completion.routine", queue_number=queue_number)
    return _question_payload(
        session,
        reply=reply,
        user_display=user_display,
        completed=True,
        queue_number=queue_number,
    )


async def _complete_urgent_consultation(
    session: dict,
    user_display: str,
    background_tasks: BackgroundTasks,
) -> dict:
    """Persist urgent safety output, then generate AI summaries in background."""
    data = session["data"]
    red_flags = session.get("safety_state", {}).get("red_flags", []) or session.get(
        "amie_state", {}
    ).get("red_flags", [])
    flag_labels = "、".join(flag.get("label", "") for flag in red_flags if flag.get("label"))
    questionnaire_pipeline = data.get("_interview_pipeline", {}).get("engine") == "questionnaire"
    possible_conditions = [] if questionnaire_pipeline else _urgent_possible_conditions(session)
    condition_summary = "、".join(possible_conditions)
    condition_line = (
        patient_message(
            "report.urgent_condition_line",
            condition_summary=condition_summary,
        )
        if condition_summary
        else ""
    )
    report = patient_message(
        "report.urgent",
        urgent_care_message=URGENT_CARE_MESSAGE,
        trigger_labels=flag_labels or patient_message("report.urgent_trigger_default"),
        condition_line=condition_line,
        summary_pending=patient_message("report.summary_pending"),
    )
    created = consultation_repository.create_with_identifiers(
        {
            "session_id": session["session_id"],
            "type": data.get("type", "other"),
            "reason": data.get("reason", ""),
            "summary": build_summary(data),
            "report": report,
            "data": data,
            "structured_note": (build_structured_emr(data) if questionnaire_pipeline else None),
            "structured_sources": [],
            "triage_level": "urgent",
            "status": "summary_pending",
            **session.get("_integration", {}),
        }
    )
    queue_number = created["queue_number"]
    background_tasks.add_task(
        process_background_summaries,
        created["consultation_id"],
    )
    session["step"] = -1
    session["index"] = -1
    reply = patient_message(
        "completion.urgent",
        urgent_care_message=URGENT_CARE_MESSAGE,
        queue_number=queue_number,
    )
    return _question_payload(
        session,
        reply=reply,
        user_display=user_display,
        completed=True,
        queue_number=queue_number,
    )


async def _complete_urgent_chief_complaint(
    session: dict,
    *,
    user_input: str,
    route: str | None,
    red_flags: list[dict[str, object]],
    background_tasks: BackgroundTasks,
) -> dict:
    """Persist a severe chief complaint before classification or planning."""
    resolved_route = str(route) if route in SUPPORTED_PATIENT_ROUTES else "other"
    data = session["data"]
    data["reason"] = user_input
    data["type"] = resolved_route
    if resolved_route != "other":
        session["questionnaire"] = build_questionnaire(resolved_route)
    disease_assessment = attach_safety_conditions(
        resolved_route,
        red_flags,
        facts=data.get("_clinical_facts", []),
    )
    data["_disease_assessment"] = disease_assessment
    state = {
        "triage_level": "urgent",
        "red_flags": red_flags,
        "differential_hypotheses": [],
        "disease_assessment": disease_assessment,
        "clinical_facts": list(data.get("_clinical_facts", [])),
        "knowledge_gaps": [],
        "evidence_timeline": [
            {
                "turn": 1,
                "answer_excerpt": user_input[:240],
                "safety_flags": red_flags,
                "audit_reason": "主訴入口安全規則直接觸發",
            }
        ],
        "rag_sources": [],
        "model_error": "",
    }
    session["triage_level"] = "urgent"
    session["amie_state"] = state
    data["_amie"] = {key: value for key, value in state.items() if key != "model_error"}
    session["turn_count"] = session.get("turn_count", 0) + 1
    _append_manual_amie_trace(
        session,
        current_question=CHIEF_QUESTIONNAIRE[0],
        answer=user_input,
        action="complete",
        reason=("主訴入口 Safety 層偵測到需儘早就醫的警訊，因此不進入後續問卷並立即結束問診。"),
        triage_level="urgent",
        red_flags=red_flags,
    )
    return await _complete_urgent_consultation(
        session,
        user_input,
        background_tasks,
    )


_amie_engine_instance: AMIEEngine | None = None
_chief_extractor_instance: ChiefComplaintExtractor | None = None


def _get_chief_extractor() -> ChiefComplaintExtractor:
    global _chief_extractor_instance
    if _chief_extractor_instance is None:
        _chief_extractor_instance = ChiefComplaintExtractor(llm_client)
    return _chief_extractor_instance


def _assess_chief_complaint(
    text: str,
    data: dict,
) -> tuple[str, list[dict[str, object]]]:
    """Run raw safety, semantic extraction, structured safety, then routing."""
    route_hint = local_complaint_route(text)
    raw_flags = detect_red_flags(
        route_hint,
        text,
        {"reason": text},
    )
    if raw_flags:
        return route_hint or "other", raw_flags

    risk_profile = build_fhir_risk_profile(data)
    assessment, model_error = _get_chief_extractor().extract(text)
    assessment_payload = assessment.as_dict() if assessment else None
    data["_chief_assessment"] = {
        "extraction": assessment_payload,
        "fhir_risk_profile": risk_profile,
        "model_error": model_error,
    }

    # Semantic safety is required after the compact high-specificity raw
    # fallback. If extraction is unavailable, do not silently continue as a
    # routine interview.
    if not assessment:
        data["_chief_assessment"]["requires_handoff"] = True
        return "safety_unavailable", []

    data["_clinical_facts"] = merge_facts(
        data.get("_clinical_facts", []),
        facts_from_assessment(
            assessment,
            turn=1,
            source="chief_semantic_extraction",
        ),
    )

    ranked_routes = prioritized_routes(assessment, risk_profile)
    data["_chief_assessment"]["route_priority"] = ranked_routes
    data["_chief_assessment"]["secondary_routes"] = ranked_routes[1:]

    raw_route_flags = [
        flag
        for candidate in ranked_routes
        for flag in detect_red_flags(candidate, text, {"reason": text})
    ]
    structured_flags = detect_structured_red_flags(assessment, risk_profile, route_hint)
    for symptom in assessment.symptom_assessments:
        scoped_assessment = ChiefComplaintAssessment(
            primary_symptom=symptom.route,
            primary_evidence=symptom.evidence,
            primary_symptom_code=symptom.symptom_code,
            symptoms=[item for item in assessment.symptoms if item.code == symptom.symptom_code],
            onset=symptom.onset,
            course=symptom.course,
            duration=symptom.duration,
            severity=symptom.severity,
            is_new_or_changed=symptom.is_new_or_changed,
            findings=symptom.findings,
            negated_findings=symptom.negated_findings,
            route_candidates=[symptom.route],
        )
        structured_flags.extend(
            detect_structured_red_flags(scoped_assessment, risk_profile, symptom.route)
        )
    all_flags = list(
        {flag["code"]: flag for flag in [*raw_route_flags, *structured_flags]}.values()
    )
    if all_flags:
        data["_chief_assessment"]["safety_flags"] = all_flags
        return (
            route_hint or preferred_route(assessment, risk_profile) or "other",
            all_flags,
        )

    # Successful semantic extraction is authoritative for questionnaire
    # eligibility. Do not ask a second, unconstrained classifier to turn an
    # associated finding (for example dizziness) into a pain complaint.
    route = route_hint or preferred_route(assessment, risk_profile) or "other"

    # The semantic extractor can discover a route that keyword matching did
    # not. Re-run the raw policy with that route before AMIE planning.
    route_flags = detect_red_flags(
        route,
        text,
        {"reason": text},
    )
    return route, route_flags


def _get_amie_engine() -> AMIEEngine:
    global _amie_engine_instance
    if _amie_engine_instance is None:
        _amie_engine_instance = AMIEEngine(llm_client)
    return _amie_engine_instance


async def _governed_route_entry(
    session: dict,
    *,
    route: str,
    user_input: str,
    user_display: str | None,
    background_tasks: BackgroundTasks,
) -> dict | None:
    """Apply urgent/manual-entry governance before any long questionnaire."""
    disposition = questionnaire_disposition(route)
    if disposition == "questionnaire":
        return None

    label = ROUTE_LABELS[route]
    flag = {
        "code": f"route_entry_{disposition}_{route}",
        "label": label,
        "scope": "route_entry",
        "route": route,
        "possible_conditions": [],
    }
    if disposition == "urgent":
        return await _complete_urgent_chief_complaint(
            session,
            user_input=user_input,
            route=route,
            red_flags=[flag],
            background_tasks=background_tasks,
        )

    session["amie_state"] = {
        "red_flags": [flag],
        "knowledge_gaps": [f"{label}需由醫療人員即時評估"],
    }
    session["turn_count"] = session.get("turn_count", 0) + 1
    _append_manual_amie_trace(
        session,
        current_question=CHIEF_QUESTIONNAIRE[0],
        answer=user_input,
        action="handoff",
        reason=f"{label}屬時效或處置敏感主訴，依路由治理停止自動問卷並轉交。",
        source="route_disposition",
        red_flags=[flag],
    )
    return await _handoff_amie_consultation(
        session,
        reason=patient_message(
            "handoff.reason.route_disposition",
            route_label=label,
        ),
        user_display=user_display,
    )


def _governed_entry_route(routes: list[str]) -> str | None:
    """Prefer urgent over handoff when several evidenced complaints coexist."""
    for disposition in ("urgent", "handoff"):
        for route in routes:
            if questionnaire_disposition(route) == disposition:
                return route
    return None


async def _handoff_amie_consultation(
    session: dict,
    *,
    reason: str,
    user_display: str | None,
) -> dict:
    data = session["data"]
    route = data.get("type", "other")
    red_flags = session.get("amie_state", {}).get("red_flags", [])
    flag_labels = "、".join(flag.get("label", "") for flag in red_flags if flag.get("label"))
    report = patient_message(
        "report.handoff",
        reason=reason,
        trigger_labels=(flag_labels or patient_message("report.handoff_trigger_default")),
    )
    created = consultation_repository.create_with_identifiers(
        {
            "session_id": session["session_id"],
            "type": route,
            "reason": data.get("reason", ""),
            "summary": build_summary(data),
            "report": report,
            "data": data,
            "triage_level": session.get("triage_level", "routine"),
            "status": "manual_handoff",
            **session.get("_integration", {}),
        }
    )
    queue_number = created["queue_number"]
    session["step"] = -1
    session["index"] = -1
    labels = flag_labels or patient_message("handoff.label_default")
    reply = patient_message(
        "handoff.reply",
        labels=labels,
        queue_number=queue_number,
    )
    return _question_payload(
        session,
        reply=reply,
        user_display=user_display,
        completed=True,
        queue_number=queue_number,
    )


async def _chat_amie(
    req: ChatRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    if req.session_id not in sessions:
        session = _amie_initial_session(req)
        sessions[req.session_id] = session
        return _question_payload(
            session,
            reply=patient_message(
                "interview.amie_welcome",
                prompt=CHIEF_QUESTIONNAIRE[0]["prompt"],
            ),
        )

    session = sessions[req.session_id]
    session["ts"] = time.time()
    if session.get("index") == -1:
        return _question_payload(
            session,
            reply=patient_message("interview.already_completed"),
            user_display=req.message or None,
            completed=True,
        )

    questionnaire = session["questionnaire"]
    index = session["index"]
    current = questionnaire[index]
    data = session["data"]
    user_input = req.message.strip()
    validation_error = validate_question_answer(
        current,
        user_input,
        pain_location_ids=req.pain_location_ids,
    )
    if validation_error:
        return _question_payload(
            session,
            reply=patient_message(
                "interview.validation_retry",
                validation_error=validation_error,
                prompt=current["prompt"],
            ),
        )

    _record_question_history(session)
    field = current["field"]
    user_input, user_display = store_question_answer(
        data,
        current,
        user_input,
        pain_location_ids=req.pain_location_ids,
    )
    if field == "reason":
        try:
            route, chief_flags = await run_clinical_io(
                _assess_chief_complaint,
                user_input,
                data,
            )
        except ClinicalOperationTimeout:
            route, chief_flags = "safety_unavailable", []
        if chief_flags:
            return await _complete_urgent_chief_complaint(
                session,
                user_input=user_input,
                route=route,
                red_flags=chief_flags,
                background_tasks=background_tasks,
            )
        data["type"] = route
        if route == "safety_unavailable":
            session["amie_state"] = {
                "red_flags": [],
                "knowledge_gaps": ["語意安全檢查未能完成"],
            }
            session["turn_count"] += 1
            _append_manual_amie_trace(
                session,
                current_question=current,
                answer=user_input,
                action="handoff",
                reason=(
                    "主訴語意安全抽取失敗，系統無法安全判斷後續路由，"
                    "因此停止自動問診並轉交醫療人員。"
                ),
                source="semantic_safety_fail_closed",
            )
            return await _handoff_amie_consultation(
                session,
                reason=patient_message("handoff.reason.safety_unavailable"),
                user_display=user_display,
            )
        if route not in SUPPORTED_PATIENT_ROUTES:
            session["amie_state"] = {
                "red_flags": [],
                "knowledge_gaps": ["目前系統不支援此主訴路由"],
            }
            session["turn_count"] += 1
            _append_manual_amie_trace(
                session,
                current_question=current,
                answer=user_input,
                action="handoff",
                reason=(
                    f"主訴被分類為 {route or 'unknown'}，無法對應已核准的"
                    "問卷路由，因此轉交醫療人員。"
                ),
                source="route_guard",
            )
            return await _handoff_amie_consultation(
                session,
                reason=patient_message("handoff.reason.unsupported_route"),
                user_display=user_display,
            )
        routes = _complaint_routes(data, route)
        data["types"] = routes
        governed_route = _governed_entry_route(routes)
        if governed_route:
            data["type"] = governed_route
            governed_response = await _governed_route_entry(
                session,
                route=governed_route,
                user_input=user_input,
                user_display=user_display,
                background_tasks=background_tasks,
            )
            if governed_response is not None:
                return governed_response
        questionnaire = build_questionnaire(routes)
        _apply_chief_questionnaire_prefills(data, questionnaire)
        questionnaire = [
            filtered
            for item in questionnaire
            if (
                filtered := filter_question_by_known_facts(
                    item,
                    data.get("_clinical_facts", []),
                )
            )
            is not None
        ]
        session["questionnaire"] = questionnaire
        _copy_prefills_to_secondary_routes(session, questionnaire)
        index = -1

    session["turn_count"] += 1

    try:
        result = await run_clinical_io(
            _get_amie_engine().run_turn,
            route=current.get("route") or data.get("type", ""),
            answer=user_input,
            current_field=field,
            data=data,
            questionnaire=questionnaire,
            prefilled_fields=set(session.get("prefilled_fields", [])),
            turn_count=session["turn_count"],
            previous_state=session.get("amie_state"),
        )
    except ClinicalOperationTimeout:
        return await _handoff_amie_consultation(
            session,
            reason=patient_message("handoff.reason.processing_timeout"),
            user_display=user_display,
        )
    session["data"] = result.data
    data = session["data"]
    session["triage_level"] = result.triage_level
    _save_amie_state(session, result)
    _append_amie_trace(
        session,
        current_question=current,
        answer=user_input,
        result=result,
    )
    if result.model_error:
        safe_log("patient.amie", "failure")

    if result.triage_level == "urgent":
        return await _complete_urgent_consultation(
            session,
            user_display,
            background_tasks,
        )
    if result.action == "handoff":
        return await _handoff_amie_consultation(
            session,
            reason=result.handoff_reason or patient_message("handoff.reason.default"),
            user_display=user_display,
        )
    if result.action == "complete":
        return await _complete_consultation(
            session,
            user_display,
            background_tasks,
        )

    next_question = result.next_question
    if not next_question:
        return await _handoff_amie_consultation(
            session,
            reason=patient_message("handoff.reason.no_next_question"),
            user_display=user_display,
        )
    next_index = next(
        (
            position
            for position, item in enumerate(questionnaire)
            if item["field"] == next_question["field"]
        ),
        -1,
    )
    if next_index < 0:
        return await _handoff_amie_consultation(
            session,
            reason=patient_message("handoff.reason.unapproved_next_question"),
            user_display=user_display,
        )

    session["index"] = next_index
    questionnaire[next_index] = next_question
    session["questionnaire"] = questionnaire
    session["step"] = session["turn_count"]
    if result.acknowledgement:
        reply = patient_message(
            "interview.acknowledgement_question",
            acknowledgement=result.acknowledgement,
            prompt=next_question["prompt"],
        )
    else:
        reply = _section_transition_reply(
            current["section"],
            next_question,
            next_question.get("route") or data["type"],
            set(session.get("prefilled_fields", [])),
        )
    return _question_payload(
        session,
        reply=reply,
        user_display=user_display,
    )


def _questionnaire_initial_session(req: ChatRequest) -> dict:
    data, prefilled_fields = _prefilled_patient_data(req)
    data["_interview_pipeline"] = {
        "engine": "questionnaire",
        "routing": "deterministic_keyword_or_common_questions",
        "version": 2,
    }
    return {
        "session_id": req.session_id,
        "engine": "questionnaire",
        "step": 0,
        "index": 0,
        "triage_level": "routine",
        "questionnaire": list(CHIEF_QUESTIONNAIRE),
        "data": data,
        "prefilled_fields": sorted(prefilled_fields),
        "_history": [],
        "ts": time.time(),
    }


async def _chat_questionnaire(
    req: ChatRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """Advance the original-order questionnaire without AMIE or semantic extraction."""

    if req.session_id not in sessions:
        session = _questionnaire_initial_session(req)
        sessions[req.session_id] = session
        return _question_payload(
            session,
            reply=patient_message(
                "interview.legacy_welcome",
                prompt=CHIEF_QUESTIONNAIRE[0]["prompt"],
            ),
        )

    session = sessions[req.session_id]
    session["ts"] = time.time()
    if session.get("index") == -1:
        return _question_payload(
            session,
            reply=patient_message("interview.already_completed"),
            user_display=req.message or None,
            completed=True,
        )

    questionnaire = session["questionnaire"]
    index = session["index"]
    current = questionnaire[index]
    data = session["data"]
    user_input = req.message.strip()
    validation_error = validate_question_answer(
        current,
        user_input,
        pain_location_ids=req.pain_location_ids,
    )
    if validation_error:
        return _question_payload(
            session,
            reply=patient_message(
                "interview.validation_retry",
                validation_error=validation_error,
                prompt=current["prompt"],
            ),
        )

    _record_question_history(session)
    field = current["field"]
    user_input, user_display = store_question_answer(
        data,
        current,
        user_input,
        pain_location_ids=req.pain_location_ids,
    )

    if field == "reason":
        route = local_complaint_route(user_input)
        data["type"] = route or "other"
        data["types"] = [route] if route else []
        questionnaire = (
            build_questionnaire(route)
            if route in SUPPORTED_PATIENT_ROUTES
            else [
                *deepcopy(CHIEF_QUESTIONNAIRE),
                *deepcopy(BASIC_QUESTIONNAIRE),
                *deepcopy(HISTORY_QUESTIONNAIRE),
            ]
        )
        session["questionnaire"] = questionnaire
        index = 0

    prefilled_fields = set(session.get("prefilled_fields", []))
    next_index = next_question_index(
        questionnaire,
        index,
        data,
        skip_fields=prefilled_fields,
    )
    if next_index is None:
        return await _complete_consultation(
            session,
            user_display,
            background_tasks,
        )

    session["index"] = next_index
    session["step"] = next_index
    next_question = questionnaire[next_index]
    return _question_payload(
        session,
        reply=_section_transition_reply(
            current["section"],
            next_question,
            next_question.get("route") or data["type"],
            prefilled_fields,
        ),
        user_display=user_display,
    )


async def _chat_impl(req: ChatRequest, background_tasks: BackgroundTasks):
    _cleanup_sessions()

    patient_session = current_patient_session()
    if patient_session is not None:
        req.session_id = patient_session["interview_session_id"]
        req.patient_prefill = PatientPrefill(**patient_session["prefill"])

    if req.action == "back" and req.session_id in sessions:
        return _restore_previous_question(sessions[req.session_id])

    if INTERVIEW_ENGINE == "amie":
        response = await _chat_amie(req, background_tasks)
    else:
        response = await _chat_questionnaire(req, background_tasks)

    if patient_session is not None and req.session_id in sessions:
        sessions[req.session_id]["_integration"] = {
            "invitation_id": patient_session["invite_id"],
            "institution_id": patient_session["institution_id"],
            "patient_sno": patient_session["patient_sno"],
            "reg_sno": patient_session["reg_sno"],
        }
    return response


def _patient_runtime_binding(patient_session: dict) -> dict[str, str]:
    return {
        "patient_session_id": patient_session["session_id"],
        "interview_session_id": patient_session["interview_session_id"],
        "institution_id": patient_session["institution_id"],
        "patient_sno": patient_session["patient_sno"],
    }


async def _chat_serialized(
    req: ChatRequest,
    background_tasks: BackgroundTasks,
    patient_session: dict | None,
):
    if patient_session is None:
        # Kept for direct unit calls; HTTP requests always install the required
        # cookie-backed patient session dependency above.
        return await _chat_impl(req, background_tasks)

    binding = _patient_runtime_binding(patient_session)
    interview_session_id = binding["interview_session_id"]
    req.session_id = interview_session_id
    req.patient_prefill = PatientPrefill(**patient_session["prefill"])

    if interview_session_id not in sessions:
        restored = consultation_repository.load_patient_runtime_state(**binding)
        if restored is not None:
            sessions[interview_session_id] = restored

    try:
        result = await _chat_impl(req, background_tasks)
    except Exception as error:
        audit_patient("patient.chat", "failure", patient_session)
        safe_log("patient.chat", "failure", error=error)
        raise
    else:
        audit_patient("patient.chat", "success", patient_session)
        return result
    finally:
        state = sessions.get(interview_session_id)
        if state is not None:
            consultation_repository.save_patient_runtime_state(
                **binding,
                state=state,
            )


@router.post(
    "/chat",
    response_model=PatientChatResponse,
    responses=error_responses(422, 500, 503),
    summary="Advance or start a patient pre-consultation interview",
    dependencies=[Depends(require_patient_session)],
)
async def chat(req: ChatRequest, background_tasks: BackgroundTasks):
    """Serialize, restore, and durably save one patient interview."""
    patient_session = current_patient_session()
    lock_id = (
        patient_session["interview_session_id"] if patient_session is not None else req.session_id
    )
    lock = _patient_chat_locks.setdefault(lock_id, asyncio.Lock())
    async with lock:
        return await _chat_serialized(req, background_tasks, patient_session)
