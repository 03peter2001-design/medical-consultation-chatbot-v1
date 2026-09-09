"""Physician consultation browsing and RAG chat endpoints."""

from __future__ import annotations

import os
import re
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
    FhirCompositionCreateResponse,
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
    FhirCompositionCreateRequest,
    LoadPatientRequest,
    SafetyRuleAssistantRequest,
    SafetyRuleUpdateRequest,
)
from app.prompts.doctor import (
    DOCTOR_SYSTEM_PROMPT,
    STRUCTURED_NOTE_TASKS,
    build_structured_note_prompt,
    parse_structured_note_response,
    render_structured_note_responses,
)
from app.security import UccPrincipal, current_ucc_principal, require_scopes
from app.services.async_clinical_io import (
    ClinicalOperationTimeout,
    run_clinical_io,
)
from app.services.clinical_summary import (
    clinical_patient_data,
    model_patient_summary,
)
from app.services.fhir_composition import build_tw_core_composition
from app.services.rag import (
    deduplicate_sources,
    retrieve_context_block,
    retrieve_knowledge_base_block,
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
from infrastructure.fhir_client import FhirClientError

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


FHIR_AUTHOR_REFERENCE_PATTERN = re.compile(
    r"(?:Practitioner|PractitionerRole)/[A-Za-z0-9\-.]{1,64}"
)
FHIR_AUTHOR_ABSOLUTE_REFERENCE_PATTERN = re.compile(
    r"https?://[^\s?#]+/(?:Practitioner|PractitionerRole)/[A-Za-z0-9\-.]{1,64}"
)


def _composition_author(principal: UccPrincipal) -> dict[str, str | None]:
    claimed_reference = str(
        principal.claims.get("fhirUser") or principal.claims.get("fhir_user") or ""
    ).strip()
    if claimed_reference and (
        FHIR_AUTHOR_REFERENCE_PATTERN.fullmatch(claimed_reference)
        or FHIR_AUTHOR_ABSOLUTE_REFERENCE_PATTERN.fullmatch(claimed_reference)
    ):
        return {
            "reference": claimed_reference,
            "identifier": None,
            "display": str(principal.claims.get("name") or principal.subject)[:200],
        }

    local_author_enabled = os.getenv(
        "FHIR_LOCAL_DEVELOPMENT_AUTHOR",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    if principal.claims.get("legacy_frontend_bypass") is True and local_author_enabled:
        return {
            "reference": None,
            "identifier": principal.subject,
            "display": "Local development clinician",
        }
    raise HTTPException(
        status_code=403,
        detail="登入身分缺少可驗證的 Practitioner／PractitionerRole",
    )


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
        raise HTTPException(status_code=422, detail="SNOMED CT 查詢條件不正確") from error
    except RuntimeError as error:
        raise HTTPException(
            status_code=503,
            detail="SNOMED CT 術語服務暫時無法使用",
        ) from error


def _rule_permission_error(error: PermissionError) -> HTTPException:
    status = 503 if "尚未設定" in str(error) else 403
    detail = "規則管理尚未設定" if status == 503 else "規則管理授權失敗"
    return HTTPException(status_code=status, detail=detail)


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
        raise HTTPException(status_code=422, detail="規則助理草稿未通過驗證") from error
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail="規則微調助理暫時無法使用",
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
        raise HTTPException(status_code=409, detail="Safety 規則版本衝突，請重新載入") from error
    except ValueError as error:
        _audit_rule_write("failure", "safety")
        raise HTTPException(status_code=422, detail="Safety 規則內容未通過驗證") from error


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
        raise HTTPException(
            status_code=409, detail="ClinicalFact 標籤版本衝突，請重新載入"
        ) from error
    except ValueError as error:
        _audit_rule_write("failure", "fact_labels")
        raise HTTPException(status_code=422, detail="ClinicalFact 標籤未通過驗證") from error


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
        raise HTTPException(status_code=409, detail="疾病表版本衝突，請重新載入") from error
    except ValueError as error:
        _audit_rule_write("failure", f"disease_profile:{route}")
        raise HTTPException(status_code=422, detail="疾病表內容未通過驗證") from error


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
                isinstance(candidate, tuple) and len(candidate) == 3 and candidate[2] == session_id
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


@router.post(
    "/consultations/{consultation_id}/fhir-composition",
    response_model=FhirCompositionCreateResponse,
    responses=error_responses(403, 404, 409, 422, 503),
    summary="Create a clinician-reviewed TW Core Composition",
    dependencies=[Depends(require_scopes("consultation:fhir-write"))],
)
def create_fhir_composition(
    consultation_id: str,
    request: FhirCompositionCreateRequest,
):
    principal = _doctor_principal()
    normalized = consultation_id.strip()[:32]
    try:
        record = runtime.consultation_repository.get(
            normalized,
            institution_id=_consultation_institution_scope(principal),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail="病例識別資料格式不正確") from error
    if not record:
        audit_ucc(
            "doctor.consultation.fhir_write",
            "denied",
            principal,
            resource_type="consultation",
            resource_id=normalized,
        )
        raise HTTPException(status_code=404, detail="查無此病例")
    existing = record.get("fhir_submission")
    context = record.get("fhir_context")
    if not context:
        raise HTTPException(status_code=409, detail="此病例沒有可信任的 FHIR 病患綁定")
    if existing:
        return {
            "status": "existing",
            "resource_id": existing["resource_id"],
            "version_id": existing["version_id"],
            "submitted_at": existing["submitted_at"],
            "patient_reference": f"Patient/{context['patient_id']}",
            "encounter_reference": (
                f"Encounter/{context['encounter_id']}" if context.get("encounter_id") else None
            ),
        }
    if record["updated_at"] != request.expected_updated_at:
        raise HTTPException(status_code=409, detail="病例已更新，請重新載入後再送出")
    if not runtime.fhir_client.enabled:
        raise HTTPException(status_code=503, detail="FHIR 寫入服務尚未啟用")

    configured_issuer = (
        os.getenv("FHIR_PUBLIC_ISSUER", "").strip().rstrip("/") or runtime.fhir_client.base_url
    )
    if context["issuer"].rstrip("/") != configured_issuer:
        raise HTTPException(status_code=409, detail="病例的 FHIR issuer 與寫入服務不一致")

    author = _composition_author(principal)
    composition = build_tw_core_composition(
        consultation_id=f"{principal.institution_id}:{normalized}",
        patient_id=context["patient_id"],
        encounter_id=context.get("encounter_id"),
        sections=request.sections,
        author_reference=author["reference"],
        author_identifier=author["identifier"],
        author_display=author["display"] or principal.subject,
        identifier_system=os.getenv(
            "FHIR_COMPOSITION_IDENTIFIER_SYSTEM",
            "https://medical-consultation.local/fhir/consultations",
        ).strip(),
        clinician_identifier_system=os.getenv(
            "FHIR_CLINICIAN_IDENTIFIER_SYSTEM",
            "https://medical-consultation.local/fhir/clinicians",
        ).strip(),
    )
    try:
        runtime.fhir_client.read_resource("Patient", context["patient_id"])
        if context.get("encounter_id"):
            runtime.fhir_client.read_resource("Encounter", context["encounter_id"])
        result = runtime.fhir_client.create_composition(composition)
        submitted_at = runtime.consultation_repository.save_fhir_submission(
            normalized,
            resource_id=result.resource_id,
            version_id=result.version_id,
            submitted_by=principal.subject,
            sections=[section.model_dump() for section in request.sections],
        )
        if not submitted_at:
            raise RuntimeError("consultation disappeared after FHIR write")
    except FhirClientError as error:
        audit_ucc(
            "doctor.consultation.fhir_write",
            "failure",
            principal,
            resource_type="consultation",
            resource_id=normalized,
        )
        safe_log("doctor.consultation.fhir_write", "failure", error=error)
        if error.status_code == 404:
            raise HTTPException(
                status_code=422,
                detail="FHIR Patient／Encounter 參照不存在",
            ) from error
        raise HTTPException(status_code=503, detail="FHIR 寫入服務暫時無法使用") from error
    except Exception as error:
        audit_ucc(
            "doctor.consultation.fhir_write",
            "failure",
            principal,
            resource_type="consultation",
            resource_id=normalized,
        )
        safe_log("doctor.consultation.fhir_write", "failure", error=error)
        raise

    audit_ucc(
        "doctor.consultation.fhir_write",
        "success",
        principal,
        resource_type="consultation",
        resource_id=normalized,
    )
    return {
        "status": "created" if result.created else "existing",
        "resource_id": result.resource_id,
        "version_id": result.version_id,
        "submitted_at": submitted_at,
        "patient_reference": f"Patient/{context['patient_id']}",
        "encounter_reference": (
            f"Encounter/{context['encounter_id']}" if context.get("encounter_id") else None
        ),
    }


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
        raise HTTPException(status_code=422, detail="病例識別資料格式不正確") from error
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
        request.consultation_id or request.registration_number or request.queue_number or "unknown"
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
        duplicate = "跨日期重複" in str(error)
        status_code = 409 if duplicate else 422
        detail = (
            "此掛號編號跨日期重複，請指定看診日期或 consultation_id"
            if duplicate
            else "病例識別資料格式不正確"
        )
        raise HTTPException(status_code=status_code, detail=detail) from error
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
    questionnaire_safety = dict(stored_data.get("_safety") or {})
    if questionnaire_safety:
        amie_state["red_flags"] = list(questionnaire_safety.get("red_flags") or [])
        amie_state["safety_source"] = questionnaire_safety.get("source", "raw_text_rules")
    legacy_differentials = list(amie_state.get("differential_hypotheses") or [])
    disease_assessment = dict(
        stored_data.get("_disease_assessment") or amie_state.get("disease_assessment") or {}
    )
    route = record.get("type")
    questionnaire_pipeline = (
        stored_data.get("_interview_pipeline", {}).get("engine") == "questionnaire"
    )
    uses_disease_vote = (
        not questionnaire_pipeline
        and route in DISEASE_ROUTES
        and load_questionnaire_policy(route)["selection_strategy"] == "disease_vote"
    )
    red_flags = list(amie_state.get("red_flags") or [])
    if (
        not questionnaire_pipeline
        and red_flags
        and not disease_assessment.get("safety_triggered_conditions")
    ):
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
        "updated_at": record.get("updated_at", record["created_at"]),
        "fhir_context": record.get("fhir_context"),
        "fhir_submission": (
            {
                "resource_id": record["fhir_submission"]["resource_id"],
                "version_id": record["fhir_submission"]["version_id"],
                "submitted_at": record["fhir_submission"]["submitted_at"],
            }
            if record.get("fhir_submission")
            else None
        ),
        "fhir_summary_sections": record.get("fhir_summary_sections") or [],
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
        diag_context, diag_sources = retrieve_knowledge_base_block(
            "A",
            f"{base_query} 鑑別診斷 危險徵兆 紅旗症狀",
            n_results=5,
            primary_route=primary_route,
            patient_data=patient_data,
        )
        lab_context, lab_sources = retrieve_knowledge_base_block(
            "B",
            f"{base_query} 抽血檢驗 實驗室檢查",
            n_results=4,
            primary_route=primary_route,
            patient_data=patient_data,
        )
        imaging_context, imaging_sources = retrieve_knowledge_base_block(
            "C",
            f"{base_query} 影像學 X光 電腦斷層 CT MRI 超音波",
            n_results=4,
            primary_route=primary_route,
            patient_data=patient_data,
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

    if request.mode != "structured_note":
        patient_block = ""
        if patient:
            patient_block = f"""目前正在討論的病人：

{model_patient_summary(patient)}

【AI初步評估】
{patient["report"]}

---

"""
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
        if request.mode == "structured_note":
            raw_responses: dict[str, str] = {}
            focus_conditions = ""
            for task in STRUCTURED_NOTE_TASKS:
                prompt_request = build_structured_note_prompt(
                    task,
                    request.message,
                    patient,
                    diag_context,
                    lab_context,
                    imaging_context,
                    focus_conditions=focus_conditions,
                )
                raw_response = await run_clinical_io(
                    runtime.llm_client.generate_text,
                    prompt_request.messages,
                    temperature=0.2,
                    max_tokens=prompt_request.max_tokens,
                )
                validated_content = parse_structured_note_response(task, raw_response)
                raw_responses[task] = raw_response
                if task == "must_not_miss":
                    focus_conditions = validated_content
            reply = render_structured_note_responses(raw_responses)
        else:
            reply = await run_clinical_io(
                runtime.llm_client.generate_text,
                messages,
                temperature=0.2,
                max_tokens=max_tokens,
            )
    except ClinicalOperationTimeout as error:
        audit_ucc(
            "doctor.consultation.chat",
            "failure",
            principal,
            resource_type="doctor_session",
            resource_id=request.session_id,
        )
        safe_log("doctor.consultation.chat", "timeout", error=error)
        raise HTTPException(
            status_code=503,
            detail="AI 生成逾時，請稍後重試",
        ) from error
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
            detail="AI 生成失敗，請稍後重試",
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
