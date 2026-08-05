"""Physician consultation browsing and RAG chat endpoints."""

from __future__ import annotations

import time
import traceback

from fastapi import APIRouter, Header, HTTPException, Query

from amie.clinical_facts import facts_from_legacy_data
from amie.disease_profiles import (
    attach_profile_codings,
    attach_safety_conditions,
    score_diseases,
)
from app import runtime
from app.contracts import (
    ConsultationDeletedResponse,
    ConsultationListResponse,
    DoctorChatResponse,
    LoadPatientResponse,
    RuleAssistantResponse,
    RuleAuthorizationResponse,
    RuleCenterResponse,
    SessionClearedResponse,
    SnomedSearchResponse,
    StatusResponse,
    error_responses,
)
from app.models import (
    DiseaseProfileUpdateRequest,
    DoctorChatRequest,
    FactLabelUpdateRequest,
    LoadPatientRequest,
    SafetyRuleAssistantRequest,
    SafetyRuleUpdateRequest,
)
from app.prompts.doctor import (
    DOCTOR_SYSTEM_PROMPT,
    STRUCTURED_NOTE_SYSTEM_PROMPT,
    build_structured_note_prompt,
)
from app.services.clinical_summary import (
    clinical_patient_data,
    model_patient_summary,
)
from app.services.rag import (
    deduplicate_sources,
    retrieve_context_block,
)
from app.services.rule_management import (
    authorize_rule_editor,
    rule_center_payload,
    suggest_safety_rule_edits,
    update_disease_profile,
    update_fact_labels,
    update_safety_rules,
)
from app.services.snomed_search import search_snomed
from domain.questionnaires import (
    DISEASE_ROUTES,
    load_questionnaire_policy,
)
from domain.terminology_reference import (
    filter_supported_codings,
    terminology_reference,
)

router = APIRouter(prefix="/doctor", tags=["doctor"])


@router.get(
    "/rules",
    response_model=RuleCenterResponse,
    summary="Read the governed Safety, fact, and disease rule center",
)
def get_rule_center():
    return rule_center_payload()


@router.get(
    "/terminology/snomed",
    response_model=SnomedSearchResponse,
    responses=error_responses(422, 503),
    summary="Search the configured SNOMED CT terminology index",
)
def get_snomed_search(
    query: str = Query(min_length=2, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
):
    try:
        return search_snomed(query, limit=limit, offset=offset)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(
            status_code=503,
            detail=f"SNOMED CT 術語服務暫時無法使用：{error}",
        ) from error


def _rule_permission_error(error: PermissionError) -> HTTPException:
    status = 503 if "尚未設定" in str(error) else 403
    return HTTPException(status_code=status, detail=str(error))


@router.post(
    "/rules/authorize",
    response_model=RuleAuthorizationResponse,
    responses=error_responses(403, 503),
    summary="Verify a rule administrator token",
)
def post_rule_authorization(
    x_rule_admin_token: str = Header(default=""),
):
    try:
        return authorize_rule_editor(x_rule_admin_token)
    except PermissionError as error:
        raise _rule_permission_error(error) from error


@router.post(
    "/rules/assistant",
    response_model=RuleAssistantResponse,
    responses=error_responses(403, 422, 503),
    summary="Generate a validated, unsaved Safety rule draft",
)
def post_rule_assistant(
    request: SafetyRuleAssistantRequest,
    x_rule_admin_token: str = Header(default=""),
):
    try:
        authorize_rule_editor(x_rule_admin_token)
        return suggest_safety_rule_edits(
            llm_client=runtime.llm_client,
            message=request.message,
            selected_labels=request.selected_labels,
            groups=[group.model_dump(exclude_none=True) for group in request.safety_groups],
            history=[item.model_dump() for item in request.history],
        )
    except PermissionError as error:
        raise _rule_permission_error(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"規則微調助理暫時無法使用：{type(error).__name__}",
        ) from error


@router.put(
    "/rules/safety",
    response_model=RuleCenterResponse,
    responses=error_responses(403, 409, 422, 503),
    summary="Publish clinician-reviewed Safety rule changes",
)
def put_safety_rules(
    request: SafetyRuleUpdateRequest,
    x_rule_admin_token: str = Header(default=""),
):
    try:
        return update_safety_rules(
            admin_token=x_rule_admin_token,
            expected_revision=request.expected_revision,
            confirmation=request.confirmation,
            change_note=request.change_note,
            actor_session_id=request.session_id,
            groups=[group.model_dump(exclude_none=True) for group in request.safety_groups],
        )
    except PermissionError as error:
        raise _rule_permission_error(error) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.put(
    "/rules/fact-labels",
    response_model=RuleCenterResponse,
    responses=error_responses(403, 409, 422, 503),
    summary="Publish clinician-reviewed ClinicalFact label changes",
)
def put_fact_labels(
    request: FactLabelUpdateRequest,
    x_rule_admin_token: str = Header(default=""),
):
    try:
        return update_fact_labels(
            admin_token=x_rule_admin_token,
            expected_revision=request.expected_revision,
            confirmation=request.confirmation,
            change_note=request.change_note,
            actor_session_id=request.session_id,
            labels=[item.model_dump() for item in request.fact_labels],
        )
    except PermissionError as error:
        raise _rule_permission_error(error) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.put(
    "/rules/disease-profiles/{route}",
    response_model=RuleCenterResponse,
    responses=error_responses(403, 409, 422, 503),
    summary="Publish clinician-reviewed disease profile changes",
)
def put_disease_profile(
    route: str,
    request: DiseaseProfileUpdateRequest,
    x_rule_admin_token: str = Header(default=""),
):
    try:
        return update_disease_profile(
            route=route,
            admin_token=x_rule_admin_token,
            expected_revision=request.expected_revision,
            confirmation=request.confirmation,
            change_note=request.change_note,
            reviewer=request.reviewer,
            actor_session_id=request.session_id,
            profiles=[profile.model_dump() for profile in request.profiles],
        )
    except PermissionError as error:
        raise _rule_permission_error(error) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _cleanup_sessions() -> None:
    now = time.time()
    expired = [
        session_id
        for session_id, session in runtime.doctor_sessions.items()
        if now - session.get("ts", 0) > runtime.DOCTOR_SESSION_TTL
    ]
    for session_id in expired:
        del runtime.doctor_sessions[session_id]


@router.get(
    "/consultations",
    response_model=ConsultationListResponse,
    responses=error_responses(422),
    summary="List searchable consultation summaries",
)
def list_consultations(
    search: str = Query(default="", max_length=100),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return runtime.consultation_repository.list_summaries(
        search=search,
        limit=limit,
        offset=offset,
    )


@router.delete(
    "/consultations/{consultation_id}",
    response_model=ConsultationDeletedResponse,
    responses=error_responses(400, 404, 422),
    summary="Permanently delete a consultation",
)
def delete_consultation(consultation_id: str):
    normalized = consultation_id.strip()[:32]
    if not normalized:
        raise HTTPException(status_code=400, detail="consultation_id 不可為空")
    try:
        record = runtime.consultation_repository.get(normalized)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not record or not runtime.consultation_repository.delete(normalized):
        raise HTTPException(status_code=404, detail="查無此病例")

    for session in runtime.doctor_sessions.values():
        patient = session.get("patient")
        if patient and patient.get("consultation_id") == normalized:
            session["patient"] = None
            session["history"] = []
    return {
        "status": "deleted",
        "consultation_id": normalized,
        "consultation_date": record["consultation_date"],
        "registration_number": record["registration_number"],
        "queue_number": record["queue_number"],
    }


@router.post(
    "/load_patient",
    response_model=LoadPatientResponse,
    responses=error_responses(
        404,
        409,
        422,
        descriptions={
            409: (
                "The supplied registration number matches consultations on multiple "
                "dates. Provide consultation_date or the composite consultation_id."
            ),
        },
    ),
    summary="Load a consultation into a physician session",
)
def load_patient(request: LoadPatientRequest):
    try:
        if request.consultation_id:
            record = runtime.consultation_repository.get(request.consultation_id)
        else:
            record = runtime.consultation_repository.get_by_registration_number(
                request.registration_number or request.queue_number or "",
                consultation_date=request.consultation_date,
            )
    except ValueError as error:
        status_code = 409 if "跨日期重複" in str(error) else 422
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    if not record:
        raise HTTPException(
            status_code=404,
            detail="查無此問診編號，請確認編號是否正確",
        )

    session = runtime.doctor_sessions.setdefault(
        request.session_id,
        {"history": [], "ts": time.time(), "patient": None},
    )
    session["ts"] = time.time()
    session["patient"] = record
    session["history"] = []

    structured_note = record.get("structured_note")
    structured_sources = list(record.get("structured_sources") or [])
    if structured_note:
        session["history"].append(
            {
                "user": "（系統預先產生）六段式結構化病歷分析",
                "assistant": structured_note,
            }
        )

    patient_data = {
        key: value
        for key, value in (record.get("data") or {}).items()
        if not key.startswith("_") and key != "pain_locations"
    }
    stored_data = record.get("data", {})
    amie_state = dict(stored_data.get("_amie") or {})
    legacy_differentials = list(amie_state.get("differential_hypotheses") or [])
    disease_assessment = dict(
        stored_data.get("_disease_assessment") or amie_state.get("disease_assessment") or {}
    )
    route = record.get("type")
    uses_disease_vote = (
        route in DISEASE_ROUTES
        and load_questionnaire_policy(route)["selection_strategy"] == "disease_vote"
    )
    red_flags = list(amie_state.get("red_flags") or [])
    if red_flags and not disease_assessment.get("safety_triggered_conditions"):
        disease_assessment = attach_safety_conditions(
            str(route or ""),
            red_flags,
            facts=facts_from_legacy_data(stored_data),
            computed_from="legacy_recalculation",
            assessment=disease_assessment or None,
        )
    elif uses_disease_vote and not disease_assessment:
        disease_assessment = score_diseases(
            facts_from_legacy_data(stored_data),
            route=str(route),
            computed_from="legacy_recalculation",
        )
    disease_assessment = attach_profile_codings(
        str(route or ""),
        disease_assessment,
    )
    amie_state["differential_hypotheses"] = []
    amie_state["disease_assessment"] = disease_assessment
    return {
        "consultation_id": record["consultation_id"],
        "consultation_date": record["consultation_date"],
        "registration_number": record["registration_number"],
        "queue_number": record["queue_number"],
        "type": record["type"],
        "reason": record["reason"],
        "patient_data": patient_data,
        "clinical_codings": filter_supported_codings(
            record.get("data", {}).get("_clinical_codings", [])
        ),
        "terminology_reference": terminology_reference(),
        "summary": record["summary"],
        "report": record["report"],
        "structured_note": structured_note,
        "structured_sources": structured_sources,
        "pain_locations": record.get("data", {}).get("pain_locations", []),
        "amie_state": amie_state,
        "disease_assessment": disease_assessment,
        "legacy_differential_hypotheses": legacy_differentials,
        "amie_trace": record.get("data", {}).get("_amie_trace", []),
        "chief_assessment": record.get("data", {}).get("_chief_assessment"),
        "triage_level": record.get("triage_level", "routine"),
        "workflow_status": record.get("status", "completed"),
        "summary_error": record.get("summary_error", ""),
        "rag_enabled": runtime.RAG_ENABLED,
        "created_at": record["created_at"],
    }


@router.delete(
    "/patient/{session_id}",
    response_model=StatusResponse,
    responses=error_responses(422),
    summary="Unload the patient from a physician session",
)
def unload_patient(session_id: str):
    if session_id in runtime.doctor_sessions:
        runtime.doctor_sessions[session_id]["patient"] = None
        runtime.doctor_sessions[session_id]["history"] = []
    return {"status": "ok"}


@router.post(
    "/chat",
    response_model=DoctorChatResponse,
    responses=error_responses(400, 422, 500, 503),
    summary="Ask the physician RAG assistant about the loaded patient",
)
async def doctor_chat(request: DoctorChatRequest):
    _cleanup_sessions()
    if not request.message:
        raise HTTPException(status_code=400, detail="請輸入問題內容")

    session = runtime.doctor_sessions.setdefault(
        request.session_id,
        {"history": [], "ts": time.time(), "patient": None},
    )
    session["ts"] = time.time()
    patient = session.get("patient")

    if not runtime.RAG_ENABLED:
        raise HTTPException(
            status_code=503,
            detail=("RAG 向量庫尚未建立，請先執行 python -m scripts.ingest"),
        )

    base_query = request.message
    if patient:
        base_query = f"{request.message} {patient.get('reason', '')}"

    if request.mode == "structured_note":
        primary_route = patient.get("type") if patient else None
        patient_data = clinical_patient_data(patient.get("data")) if patient else None
        diag_context, diag_sources = retrieve_context_block(
            f"{base_query} 鑑別診斷 危險徵兆 紅旗症狀",
            n_results=5,
            primary_route=primary_route,
            patient_data=patient_data,
            purpose="diagnosis",
        )
        lab_context, lab_sources = retrieve_context_block(
            f"{base_query} 抽血檢驗 實驗室檢查",
            n_results=4,
            primary_route=primary_route,
            patient_data=patient_data,
            purpose="lab",
        )
        imaging_context, imaging_sources = retrieve_context_block(
            f"{base_query} 影像學 X光 電腦斷層 CT MRI 超音波",
            n_results=4,
            primary_route=primary_route,
            patient_data=patient_data,
            purpose="imaging",
        )
        sources = deduplicate_sources(
            diag_sources,
            lab_sources,
            imaging_sources,
        )
    else:
        context_block, sources = retrieve_context_block(
            base_query,
            n_results=6,
            primary_route=patient.get("type") if patient else None,
            patient_data=(clinical_patient_data(patient.get("data")) if patient else None),
            purpose="general",
        )

    patient_block = ""
    if patient:
        patient_block = f"""目前正在討論的病人：

{model_patient_summary(patient)}

【AI初步評估】
{patient["report"]}

---

"""

    if request.mode == "structured_note":
        user_prompt = build_structured_note_prompt(
            request.message,
            patient,
            diag_context,
            lab_context,
            imaging_context,
        )
        messages = [
            {"role": "system", "content": STRUCTURED_NOTE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        max_tokens = 1400
    else:
        messages = [{"role": "system", "content": DOCTOR_SYSTEM_PROMPT}]
        for turn in session["history"][-runtime.DOCTOR_HISTORY_MAX_TURNS :]:
            messages.append({"role": "user", "content": turn["user"]})
            messages.append({"role": "assistant", "content": turn["assistant"]})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"{patient_block}醫學知識庫內容：\n\n"
                    f"{context_block}\n\n---\n\n"
                    f"醫師的問題：{request.message}"
                ),
            }
        )
        max_tokens = 800

    try:
        reply = runtime.llm_client.generate_text(
            messages,
            temperature=0.2,
            max_tokens=max_tokens,
        )
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"AI 生成失敗：{error}",
        ) from error

    session["history"].append({"user": request.message, "assistant": reply})
    session["history"] = session["history"][-runtime.DOCTOR_HISTORY_MAX_TURNS :]
    return {
        "reply": reply,
        "session_id": request.session_id,
        "sources": sources,
        "patient_loaded": patient["queue_number"] if patient else None,
        "patient_loaded_consultation_id": (patient["consultation_id"] if patient else None),
        "mode": request.mode,
    }


@router.delete(
    "/session/{session_id}",
    response_model=SessionClearedResponse,
    responses=error_responses(422),
    summary="Clear a physician conversation session",
)
def doctor_reset(session_id: str):
    runtime.doctor_sessions.pop(session_id, None)
    return {"status": "ok", "cleared": session_id}
