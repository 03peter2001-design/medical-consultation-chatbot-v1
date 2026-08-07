"""Physician consultation browsing and RAG chat endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query

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
from app.security import UccPrincipal, current_ucc_principal, require_scopes
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
from app.services.rule_management_support.common import INTERNAL_RULE_AUTHORIZATION
from app.services.security_audit import audit_ucc, safe_log
from app.services.snomed_search import search_snomed
from domain.questionnaires import (
    DISEASE_ROUTES,
    load_questionnaire_policy,
)
from domain.terminology_reference import (
    filter_supported_codings,
    terminology_reference,
)

router = APIRouter(
    prefix="/doctor",
    tags=["doctor"],
    dependencies=[Depends(require_scopes("consultation:read"))],
)


def _consultation_institution_scope(principal: UccPrincipal) -> str | None:
    """Keep tenant isolation except for the explicit loopback legacy UI bypass."""

    if principal.claims.get("legacy_frontend_bypass") is True:
        return None
    return principal.institution_id


@router.get(
    "/rules",
    response_model=RuleCenterResponse,
    summary="Read the governed Safety, fact, and disease rule center",
    dependencies=[Depends(require_scopes("rules:read"))],
)
def get_rule_center():
    payload = rule_center_payload()
    principal = current_ucc_principal()
    if principal:
        payload["edit_enabled"] = "rules:write" in principal.scopes
    return payload


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


def _audit_rule_write(outcome: str, resource_id: str) -> None:
    principal = current_ucc_principal()
    if principal is not None:
        audit_ucc(
            "doctor.rules.write",
            outcome,
            principal,
            resource_type="rule_set",
            resource_id=resource_id,
        )


@router.post(
    "/rules/authorize",
    response_model=RuleAuthorizationResponse,
    responses=error_responses(403, 503),
    summary="Verify a rule administrator token",
    dependencies=[Depends(require_scopes("rules:read"))],
)
def post_rule_authorization():
    return authorize_rule_editor(INTERNAL_RULE_AUTHORIZATION)


@router.post(
    "/rules/assistant",
    response_model=RuleAssistantResponse,
    responses=error_responses(403, 422, 503),
    summary="Generate a validated, unsaved Safety rule draft",
    dependencies=[Depends(require_scopes("rules:write"))],
)
def post_rule_assistant(
    request: SafetyRuleAssistantRequest,
):
    try:
        authorize_rule_editor(INTERNAL_RULE_AUTHORIZATION)
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
    dependencies=[Depends(require_scopes("rules:write"))],
)
def put_safety_rules(
    request: SafetyRuleUpdateRequest,
):
    try:
        result = update_safety_rules(
            admin_token=INTERNAL_RULE_AUTHORIZATION,
            expected_revision=request.expected_revision,
            confirmation=request.confirmation,
            change_note=request.change_note,
            actor_session_id=request.session_id,
            groups=[group.model_dump(exclude_none=True) for group in request.safety_groups],
        )
        _audit_rule_write("success", "safety")
        return result
    except PermissionError as error:
        _audit_rule_write("denied", "safety")
        raise _rule_permission_error(error) from error
    except RuntimeError as error:
        _audit_rule_write("failure", "safety")
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        _audit_rule_write("failure", "safety")
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.put(
    "/rules/fact-labels",
    response_model=RuleCenterResponse,
    responses=error_responses(403, 409, 422, 503),
    summary="Publish clinician-reviewed ClinicalFact label changes",
    dependencies=[Depends(require_scopes("rules:write"))],
)
def put_fact_labels(
    request: FactLabelUpdateRequest,
):
    try:
        result = update_fact_labels(
            admin_token=INTERNAL_RULE_AUTHORIZATION,
            expected_revision=request.expected_revision,
            confirmation=request.confirmation,
            change_note=request.change_note,
            actor_session_id=request.session_id,
            labels=[item.model_dump() for item in request.fact_labels],
        )
        _audit_rule_write("success", "fact_labels")
        return result
    except PermissionError as error:
        _audit_rule_write("denied", "fact_labels")
        raise _rule_permission_error(error) from error
    except RuntimeError as error:
        _audit_rule_write("failure", "fact_labels")
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        _audit_rule_write("failure", "fact_labels")
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.put(
    "/rules/disease-profiles/{route}",
    response_model=RuleCenterResponse,
    responses=error_responses(403, 409, 422, 503),
    summary="Publish clinician-reviewed disease profile changes",
    dependencies=[Depends(require_scopes("rules:write"))],
)
def put_disease_profile(
    route: str,
    request: DiseaseProfileUpdateRequest,
):
    try:
        result = update_disease_profile(
            route=route,
            admin_token=INTERNAL_RULE_AUTHORIZATION,
            expected_revision=request.expected_revision,
            confirmation=request.confirmation,
            change_note=request.change_note,
            reviewer=request.reviewer,
            actor_session_id=request.session_id,
            profiles=[profile.model_dump() for profile in request.profiles],
        )
        _audit_rule_write("success", f"disease_profile:{route}")
        return result
    except PermissionError as error:
        _audit_rule_write("denied", f"disease_profile:{route}")
        raise _rule_permission_error(error) from error
    except RuntimeError as error:
        _audit_rule_write("failure", f"disease_profile:{route}")
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        _audit_rule_write("failure", f"disease_profile:{route}")
        raise HTTPException(status_code=422, detail=str(error)) from error


def _doctor_principal() -> UccPrincipal:
    principal = current_ucc_principal()
    if principal is None:
        # The router dependency installs this context for every HTTP request.
        # Keeping the route functions strict also prevents an internal caller
        # from accidentally treating a client session id as authorization.
        raise HTTPException(status_code=401, detail="UCC authentication required")
    return principal


def _doctor_session_key(
    session_id: str,
    principal: UccPrincipal | None = None,
) -> runtime.DoctorSessionKey:
    owner = principal or _doctor_principal()
    return (owner.institution_id, owner.subject, session_id)


def _doctor_session_not_found() -> HTTPException:
    # Deliberately identical for absent and differently-owned sessions.
    return HTTPException(status_code=404, detail="Physician session not found")


def _doctor_session(
    session_id: str,
    *,
    create: bool = False,
) -> tuple[runtime.DoctorSessionKey, dict]:
    principal = _doctor_principal()
    key = _doctor_session_key(session_id, principal)
    with runtime.doctor_sessions_lock:
        session = runtime.doctor_sessions.get(key)
        if session is None:
            # A raw id already used by another tenant/clinician is treated exactly
            # like an unavailable id.  This prevents guessing it from overwriting
            # another principal's state while returning no owner information.
            if any(
                isinstance(candidate, tuple)
                and len(candidate) == 3
                and candidate[2] == session_id
                for candidate in runtime.doctor_sessions
            ):
                audit_ucc(
                    "doctor.session.access",
                    "denied",
                    principal,
                    resource_type="doctor_session",
                    resource_id=session_id,
                )
                raise _doctor_session_not_found()
            if not create:
                audit_ucc(
                    "doctor.session.access",
                    "denied",
                    principal,
                    resource_type="doctor_session",
                    resource_id=session_id,
                )
                raise _doctor_session_not_found()
            session = {
                "history": [],
                "ts": time.time(),
                "patient": None,
                "institution_id": principal.institution_id,
                "doctor_sub": principal.subject,
            }
            runtime.doctor_sessions[key] = session
    return key, session


def _cleanup_sessions() -> None:
    now = time.time()
    with runtime.doctor_sessions_lock:
        expired = [
            session_key
            for session_key, session in runtime.doctor_sessions.items()
            if now - session.get("ts", 0) > runtime.DOCTOR_SESSION_TTL
        ]
        for session_key in expired:
            del runtime.doctor_sessions[session_key]


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
    principal = _doctor_principal()
    options = {"search": search, "limit": limit, "offset": offset}
    options["institution_id"] = _consultation_institution_scope(principal)
    try:
        result = runtime.consultation_repository.list_summaries(**options)
    except Exception as error:
        audit_ucc("doctor.consultation.list", "failure", principal)
        safe_log("doctor.consultation.list", "failure", error=error)
        raise
    audit_ucc("doctor.consultation.list", "success", principal)
    return result


@router.delete(
    "/consultations/{consultation_id}",
    response_model=ConsultationDeletedResponse,
    responses=error_responses(400, 403, 404, 422),
    summary="Permanently delete a consultation",
    dependencies=[Depends(require_scopes("consultation:delete"))],
)
def delete_consultation(consultation_id: str):
    principal = _doctor_principal()
    normalized = consultation_id.strip()[:32]
    if not normalized:
        audit_ucc(
            "doctor.consultation.delete",
            "denied",
            principal,
            resource_type="consultation",
            resource_id=consultation_id,
        )
        raise HTTPException(status_code=400, detail="consultation_id 不可為空")
    try:
        record = runtime.consultation_repository.get(
            normalized,
            institution_id=_consultation_institution_scope(principal),
        )
    except ValueError as error:
        audit_ucc(
            "doctor.consultation.delete",
            "denied",
            principal,
            resource_type="consultation",
            resource_id=normalized,
        )
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        audit_ucc(
            "doctor.consultation.delete",
            "failure",
            principal,
            resource_type="consultation",
            resource_id=normalized,
        )
        safe_log("doctor.consultation.delete", "failure", error=error)
        raise
    if not record:
        audit_ucc(
            "doctor.consultation.delete",
            "denied",
            principal,
            resource_type="consultation",
            resource_id=normalized,
        )
        raise HTTPException(status_code=404, detail="查無此病例")

    try:
        if not runtime.consultation_repository.delete(normalized):
            audit_ucc(
                "doctor.consultation.delete",
                "denied",
                principal,
                resource_type="consultation",
                resource_id=normalized,
            )
            raise HTTPException(status_code=404, detail="查無此病例")

        owner_prefix = (principal.institution_id, principal.subject)
        with runtime.doctor_sessions_lock:
            for session_key, session in runtime.doctor_sessions.items():
                if not isinstance(session_key, tuple) or session_key[:2] != owner_prefix:
                    continue
                patient = session.get("patient")
                if patient and patient.get("consultation_id") == normalized:
                    session["patient"] = None
                    session["history"] = []
    except HTTPException:
        raise
    except Exception as error:
        audit_ucc(
            "doctor.consultation.delete",
            "failure",
            principal,
            resource_type="consultation",
            resource_id=normalized,
        )
        safe_log("doctor.consultation.delete", "failure", error=error)
        raise

    audit_ucc(
        "doctor.consultation.delete",
        "success",
        principal,
        resource_type="consultation",
        resource_id=normalized,
    )
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
    principal = _doctor_principal()
    institution_id = _consultation_institution_scope(principal)
    requested_resource = (
        request.consultation_id
        or request.registration_number
        or request.queue_number
        or "unknown"
    )
    try:
        if request.consultation_id:
            record = runtime.consultation_repository.get(
                request.consultation_id,
                institution_id=institution_id,
            )
        else:
            lookup_options = {"consultation_date": request.consultation_date}
            lookup_options["institution_id"] = institution_id
            record = runtime.consultation_repository.get_by_registration_number(
                request.registration_number or request.queue_number or "",
                **lookup_options,
            )
    except ValueError as error:
        audit_ucc(
            "doctor.consultation.load",
            "failure",
            principal,
            resource_type="consultation",
            resource_id=requested_resource,
        )
        status_code = 409 if "跨日期重複" in str(error) else 422
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    if not record:
        audit_ucc(
            "doctor.consultation.load",
            "denied",
            principal,
            resource_type="consultation",
            resource_id=requested_resource,
        )
        raise HTTPException(
            status_code=404,
            detail="查無此問診編號，請確認編號是否正確",
        )

    _, session = _doctor_session(request.session_id, create=True)
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
    audit_ucc(
        "doctor.consultation.load",
        "success",
        principal,
        resource_type="consultation",
        resource_id=record["consultation_id"],
    )
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
    _, session = _doctor_session(session_id)
    session["patient"] = None
    session["history"] = []
    return {"status": "ok"}


@router.post(
    "/chat",
    response_model=DoctorChatResponse,
    responses=error_responses(400, 422, 500, 503),
    summary="Ask the physician RAG assistant about the loaded patient",
    dependencies=[Depends(require_scopes("consultation:chat"))],
)
async def doctor_chat(request: DoctorChatRequest):
    _cleanup_sessions()
    principal = _doctor_principal()
    if not request.message:
        raise HTTPException(status_code=400, detail="請輸入問題內容")

    # Chat never creates a session from a browser-chosen id.  A physician must
    # first load a consultation, so missing and differently-owned ids are both
    # indistinguishable 404 responses.
    try:
        _, session = _doctor_session(request.session_id)
    except HTTPException:
        audit_ucc(
            "doctor.consultation.chat",
            "denied",
            principal,
            resource_type="doctor_session",
            resource_id=request.session_id,
        )
        raise
    session["ts"] = time.time()
    patient = session.get("patient")

    if not runtime.RAG_ENABLED:
        audit_ucc(
            "doctor.consultation.chat",
            "failure",
            principal,
            resource_type="doctor_session",
            resource_id=request.session_id,
        )
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
        audit_ucc(
            "doctor.consultation.chat",
            "failure",
            principal,
            resource_type="doctor_session",
            resource_id=request.session_id,
        )
        safe_log("doctor.consultation.chat", "failure", error=error)
        raise HTTPException(
            status_code=500,
            detail=f"AI 生成失敗：{error}",
        ) from error

    session["history"].append({"user": request.message, "assistant": reply})
    session["history"] = session["history"][-runtime.DOCTOR_HISTORY_MAX_TURNS :]
    audit_ucc(
        "doctor.consultation.chat",
        "success",
        principal,
        resource_type="consultation",
        resource_id=(patient.get("consultation_id") if patient else request.session_id),
    )
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
    key, _ = _doctor_session(session_id)
    with runtime.doctor_sessions_lock:
        runtime.doctor_sessions.pop(key, None)
    return {"status": "ok", "cleared": session_id}
