"""Patient questionnaire and AMIE interview endpoints."""

from copy import deepcopy
import time

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
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
from app.security import current_patient_session, require_patient_session
from app.runtime import (
    AMIE_DEBUG_TRACE,
    INTERVIEW_ENGINE,
    SESSION_TTL,
    URGENT_CARE_MESSAGE,
    consultation_repository,
    llm_client,
    sessions,
)
from app.services.amie_audit import (
    append_amie_trace as _append_amie_trace,
)
from app.services.amie_audit import (
    append_manual_amie_trace as _append_manual_amie_trace,
)
from app.services.amie_audit import (
    save_amie_state as _save_amie_state,
)
from app.services.clinical_summary import build_summary
from app.services.consultation_reporting import (
    process_background_summaries,
)
from app.services.input_validation import (
    store_question_answer,
    validate_question_answer,
)
from app.services.security_audit import audit_patient, safe_log
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
from domain.questionnaires import (
    CHIEF_QUESTIONNAIRE,
    ROUTE_LABELS,
    build_questionnaire,
    condition_matches,
    filter_question_by_context,
    next_question_index,
    progress_meta,
    questionnaire_meta,
)
from domain.questionnaires import (
    question_input as structured_question_input,
)

router = APIRouter(tags=["patient"])

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
            reply="目前沒有可返回的上一題。",
            completed=session.get("index") == -1,
        )

    snapshot = history.pop()
    integration = session.get("_integration")
    transcript = session.get("transcript", [])[
        : snapshot.pop("_transcript_length", 0)
    ]
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
        reply=f"已回到上一題，您可以重新作答。\n\n{current['prompt']}",
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
            max_tokens=5,
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


async def _complete_consultation(
    session: dict,
    user_display: str,
    background_tasks: BackgroundTasks,
) -> dict:
    data = session["data"]
    ctype = data["type"]
    created = consultation_repository.create_with_identifiers(
        {
            "session_id": session["session_id"],
            "type": ctype,
            "reason": data.get("reason", ""),
            "summary": build_summary(data),
            "report": "【AI 預問診摘要】\n摘要產生中，請稍候。",
            "data": data,
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
    reply = (
        f"謝謝您的回答，問診已完成。\n\n"
        f"────────────\n"
        f"📋 您的問診編號為：{queue_number}\n"
        f"────────────\n\n"
        "請您耐心等候叫號，輪到您的號碼時醫師會與您看診。"
        "如果您感到非常不舒服，請立即告知現場護理師。"
    )
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
    red_flags = session.get("amie_state", {}).get("red_flags", [])
    flag_labels = "、".join(flag.get("label", "") for flag in red_flags if flag.get("label"))
    possible_conditions = _urgent_possible_conditions(session)
    condition_summary = "、".join(possible_conditions)
    condition_line = f"可能涉及的緊急疾病：{condition_summary}\n" if condition_summary else ""
    report = (
        "【儘早就醫警示】\n"
        f"{URGENT_CARE_MESSAGE}\n"
        f"觸發項目：{flag_labels or '問診安全規則'}\n\n"
        f"{condition_line}"
        "此內容為預問診分級提示，不是正式診斷。\n\n"
        "【AI 預問診摘要】\n摘要產生中，請稍候。"
    )
    created = consultation_repository.create_with_identifiers(
        {
            "session_id": session["session_id"],
            "type": data.get("type", "other"),
            "reason": data.get("reason", ""),
            "summary": build_summary(data),
            "report": report,
            "data": data,
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
    reply = (
        f"⚠️ {URGENT_CARE_MESSAGE}\n\n"
        "本次預問診已停止，不會再繼續追問。\n\n"
        "────────────\n"
        f"📋 您的儘早就醫編號為：{queue_number}\n"
        "────────────"
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
    report = (
        "【AMIE安全轉交】\n"
        f"{reason}\n"
        f"觸發項目：{flag_labels or '需由醫療人員進一步分流'}\n\n"
        "此內容為預問診安全提示，不是正式診斷；"
        "請由現場醫療人員進一步確認病人狀況。"
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
    labels = flag_labels or "需要進一步確認的情況"
    reply = (
        f"我注意到您提到「{labels}」。為了安全起見，"
        "一般預問診已停止，請洽現場護理師或醫師進一步確認。\n\n"
        f"您的問診編號為：{queue_number}"
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
            reply=(
                "您好！我是您的數位醫療助理。接下來會依照您的回答"
                "動態調整問題；若發現需要儘早就醫的警訊，系統會"
                "結束預問診並提供三位數編號。\n\n"
                f"{CHIEF_QUESTIONNAIRE[0]['prompt']}"
            ),
        )

    session = sessions[req.session_id]
    session["ts"] = time.time()
    if session.get("index") == -1:
        return _question_payload(
            session,
            reply="本次預問診已完成，請重新整理頁面開始新的問診。",
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
            reply=f"{validation_error}\n\n{current['prompt']}",
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
        route, chief_flags = _assess_chief_complaint(
            user_input,
            data,
        )
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
                reason=("語意安全檢查暫時無法完成，請由現場醫療人員確認"),
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
                    f"主訴被分類為 {route or 'unknown'}，不在目前核准的"
                    "胸痛、頭痛或腹痛問卷範圍，因此轉交醫療人員。"
                ),
                source="route_guard",
            )
            return await _handoff_amie_consultation(
                session,
                reason="主訴不在目前支援的胸痛、頭痛或腹痛路由",
                user_display=user_display,
            )
        routes = _complaint_routes(data, route)
        data["types"] = routes
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

    result = _get_amie_engine().run_turn(
        route=current.get("route") or data.get("type", ""),
        answer=user_input,
        current_field=field,
        data=data,
        questionnaire=questionnaire,
        prefilled_fields=set(session.get("prefilled_fields", [])),
        turn_count=session["turn_count"],
        previous_state=session.get("amie_state"),
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
            reason=result.handoff_reason or "需要醫療人員進一步確認",
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
            reason="動態問診未能選出安全的下一個問題",
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
            reason="動態問診選出的問題不在核准問題庫",
            user_display=user_display,
        )

    session["index"] = next_index
    questionnaire[next_index] = next_question
    session["questionnaire"] = questionnaire
    session["step"] = session["turn_count"]
    if result.acknowledgement:
        reply = f"{result.acknowledgement}\n\n{next_question['prompt']}"
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
        if patient_session is not None and req.session_id in sessions:
            sessions[req.session_id]["_integration"] = {
                "invitation_id": patient_session["invite_id"],
                "institution_id": patient_session["institution_id"],
                "patient_sno": patient_session["patient_sno"],
                "reg_sno": patient_session["reg_sno"],
            }
        return response

    if req.session_id not in sessions:
        data, prefilled_fields = _prefilled_patient_data(req)

        session = {
            "session_id": req.session_id,
            "engine": "legacy",
            "step": 0,
            "index": 0,
            "questionnaire": list(CHIEF_QUESTIONNAIRE),
            "data": data,
            "prefilled_fields": list(prefilled_fields),
            "_history": [],
            "ts": time.time(),
        }
        sessions[req.session_id] = session
        if patient_session is not None:
            session["_integration"] = {
                "invitation_id": patient_session["invite_id"],
                "institution_id": patient_session["institution_id"],
                "patient_sno": patient_session["patient_sno"],
                "reg_sno": patient_session["reg_sno"],
            }
        return _question_payload(
            session,
            reply=(
                "您好！我是您的數位醫療助理。請先說明主訴，"
                "之後會依序填寫基本資料、病史與症狀問卷。\n\n"
                f"{CHIEF_QUESTIONNAIRE[0]['prompt']}"
            ),
        )

    session = sessions[req.session_id]
    session["ts"] = time.time()
    if session.get("index") == -1:
        return _question_payload(
            session,
            reply="本次預問診已完成，請重新整理頁面開始新的問診。",
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
            reply=f"{validation_error}\n\n{current['prompt']}",
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
        route, chief_flags = _assess_chief_complaint(
            user_input,
            data,
        )
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
            session["step"] = -1
            session["index"] = -1
            return _question_payload(
                session,
                reply=("目前無法完成語意安全檢查，請直接由現場護理師或醫師確認後續處置。"),
                user_display=user_display,
                completed=True,
            )
        if route not in SUPPORTED_PATIENT_ROUTES:
            session["step"] = -1
            session["index"] = -1
            return _question_payload(
                session,
                reply=(
                    "了解，您描述的症狀目前不在胸痛／頭痛／腹痛問診"
                    "範圍內，建議直接由現場護理師或醫師進一步分流。"
                ),
                user_display=user_display,
                completed=True,
            )
        routes = _complaint_routes(data, route)
        data["types"] = routes
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

    previous_section = current["section"]
    session["index"] = next_index
    session["step"] = next_index
    next_question = questionnaire[next_index]
    return _question_payload(
        session,
        reply=_section_transition_reply(
            previous_section,
            next_question,
            next_question.get("route") or data["type"],
            prefilled_fields,
        ),
        user_display=user_display,
    )


def _patient_runtime_binding(patient_session: dict) -> dict[str, str]:
    return {
        "patient_session_id": patient_session["session_id"],
        "interview_session_id": patient_session["interview_session_id"],
        "institution_id": patient_session["institution_id"],
        "patient_sno": patient_session["patient_sno"],
    }


@router.post(
    "/chat",
    response_model=PatientChatResponse,
    responses=error_responses(422, 500, 503),
    summary="Advance or start a patient pre-consultation interview",
    dependencies=[Depends(require_patient_session)],
)
async def chat(req: ChatRequest, background_tasks: BackgroundTasks):
    """Restore and durably save the cookie-bound patient interview."""
    patient_session = current_patient_session()
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
