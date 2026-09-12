"""UCC-created invitations and public patient session exchange."""

from __future__ import annotations

import os
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app import runtime
from app.contracts import (
    InvitationCancelResponse,
    InvitationExchangeResponse,
    InvitationListResponse,
    InvitationResponse,
    InvitationStatus,
    LauncherInvitationResponse,
    PatientSessionResponse,
    error_responses,
)
from app.models import (
    InvitationCreateRequest,
    InvitationExchangeRequest,
    LauncherInvitationCreateRequest,
    normalize_fhir_issuer,
)
from app.security import (
    PATIENT_SESSION_COOKIE,
    UccPrincipal,
    require_patient_session,
    require_scopes,
)
from app.services.security_audit import audit_patient, audit_ucc

router = APIRouter(tags=["patient"])

_DEFAULT_LAUNCH_CODE_TTL_SECONDS = 5 * 60
_MIN_LAUNCH_CODE_TTL_SECONDS = 60
_MAX_LAUNCH_CODE_TTL_SECONDS = 60 * 60


def _secure_cookie() -> bool:
    return os.getenv("PATIENT_COOKIE_SECURE", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def require_invitation_doctor(
    principal: UccPrincipal = Depends(require_scopes("consultation:read")),
) -> UccPrincipal:
    if principal.claims.get("token_use") == "ucc_service":
        raise HTTPException(status_code=403, detail="Doctor identity required")
    return principal


def require_invitation_manager(
    principal: UccPrincipal = Depends(require_invitation_doctor),
    _: UccPrincipal = Depends(require_scopes("invite:create")),
) -> UccPrincipal:
    return principal


@router.get(
    "/doctor/invitations",
    response_model=InvitationListResponse,
    responses=error_responses(401, 403, 422),
    tags=["doctor"],
    summary="List institution invitation usage without bearer tokens",
)
def list_doctor_invitations(
    response: Response,
    status: InvitationStatus | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: UccPrincipal = Depends(require_invitation_doctor),
):
    response.headers["Cache-Control"] = "no-store"
    result = runtime.consultation_repository.list_invitations(
        institution_id=principal.institution_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    audit_ucc("doctor.invitation.list", "success", principal)
    return result


def _manage_invitation(invite_id: str, principal: UccPrincipal, *, reissue: bool):
    try:
        result = runtime.consultation_repository.manage_invitation(
            institution_id=principal.institution_id,
            invite_id=invite_id,
            actor_sub=principal.subject,
            reissue=reissue,
        )
    except ValueError as error:
        audit_ucc(
            "doctor.invitation.manage",
            "denied",
            principal,
            resource_type="invitation",
            resource_id=invite_id,
        )
        raise HTTPException(
            status_code=409,
            detail="Invitation is completed, already reissued, or conflicts with another invitation",
        ) from error
    if result is None:
        audit_ucc(
            "doctor.invitation.manage",
            "denied",
            principal,
            resource_type="invitation",
            resource_id=invite_id,
        )
        raise HTTPException(status_code=404, detail="Invitation not found")
    return result


@router.post(
    "/doctor/invitations/{invite_id}/cancel",
    response_model=InvitationCancelResponse,
    responses=error_responses(401, 403, 404, 409),
    tags=["doctor"],
    summary="Revoke an invitation and all patient sessions",
)
def cancel_doctor_invitation(
    invite_id: str,
    response: Response,
    principal: UccPrincipal = Depends(require_invitation_manager),
):
    response.headers["Cache-Control"] = "no-store"
    return _manage_invitation(invite_id, principal, reissue=False)


@router.post(
    "/doctor/invitations/{invite_id}/reissue",
    response_model=InvitationResponse,
    responses=error_responses(401, 403, 404, 409, 503),
    tags=["doctor"],
    summary="Revoke old access and issue a fresh single-use invitation",
)
def reissue_doctor_invitation(
    invite_id: str,
    response: Response,
    principal: UccPrincipal = Depends(require_invitation_manager),
):
    public_base = os.getenv("PATIENT_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not public_base.startswith("https://"):
        raise HTTPException(status_code=503, detail="HTTPS patient public URL is not configured")
    result = _manage_invitation(invite_id, principal, reissue=True)
    result["public_url"] = f"{public_base}/#token={quote(result.pop('token'))}"
    response.headers["Cache-Control"] = "no-store"
    return result


def _canonical_reg_sno_claim(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    canonical = str(value).strip()
    return canonical or None


def require_invitation_service(
    principal: UccPrincipal = Depends(require_scopes("invite:create")),
) -> UccPrincipal:
    claims = principal.claims
    if claims.get("token_use") != "ucc_service":
        raise HTTPException(status_code=403, detail="UCC service token required")

    claimed_institution = claims.get("institution_id")
    expected_subject = f"ucc-service:{principal.institution_id}"
    if claimed_institution != principal.institution_id or principal.subject != expected_subject:
        raise HTTPException(status_code=403, detail="Invalid UCC service identity")
    return principal


def require_local_fhir_launcher(
    principal: UccPrincipal = Depends(require_scopes("consultation:read", "invite:create")),
) -> UccPrincipal:
    enabled = os.getenv("LOCAL_FHIR_LAUNCHER_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not enabled:
        raise HTTPException(status_code=403, detail="Local FHIR launcher is disabled")
    if not (
        principal.claims.get("local_auth_bypass") is True
        and principal.claims.get("legacy_frontend_bypass") is True
    ):
        raise HTTPException(
            status_code=403,
            detail="Local development doctor identity required",
        )
    return principal


def _launcher_code_ttl_seconds() -> int:
    raw_value = os.getenv(
        "LOCAL_FHIR_LAUNCH_CODE_TTL_SECONDS",
        str(_DEFAULT_LAUNCH_CODE_TTL_SECONDS),
    ).strip()
    try:
        configured = int(raw_value)
    except ValueError:
        configured = _DEFAULT_LAUNCH_CODE_TTL_SECONDS
    return max(
        _MIN_LAUNCH_CODE_TTL_SECONDS,
        min(configured, _MAX_LAUNCH_CODE_TTL_SECONDS),
    )


@router.post(
    "/invitations",
    response_model=InvitationResponse,
    responses=error_responses(403, 409, 422, 503),
    summary="Create a single-use patient invitation from UCC",
)
def create_invitation(
    payload: InvitationCreateRequest,
    principal: UccPrincipal = Depends(require_invitation_service),
):
    claimed_institution = principal.claims.get("institution_id")
    if (
        payload.institution_id != principal.institution_id
        or claimed_institution != payload.institution_id
    ):
        raise HTTPException(status_code=403, detail="Institution does not match UCC token")
    if _canonical_reg_sno_claim(principal.claims.get("reg_sno")) != payload.reg_sno:
        raise HTTPException(status_code=403, detail="Encounter does not match UCC token")
    public_base = os.getenv("PATIENT_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not public_base.startswith("https://"):
        raise HTTPException(status_code=503, detail="HTTPS patient public URL is not configured")
    invitation = runtime.consultation_repository.create_invitation(
        institution_id=payload.institution_id,
        patient_sno=payload.patient_sno,
        reg_sno=payload.reg_sno,
        prefill=payload.prefill.as_patient_prefill(),
        actor_sub=principal.subject,
    )
    invitation["public_url"] = f"{public_base}/#token={quote(invitation.pop('token'))}"
    return invitation


@router.post(
    "/doctor/launcher/invitations",
    response_model=LauncherInvitationResponse,
    responses=error_responses(403, 422, 503),
    summary="Create a short-lived patient code from the local FHIR launcher",
    tags=["doctor"],
)
def create_launcher_invitation(
    payload: LauncherInvitationCreateRequest,
    response: Response,
    principal: UccPrincipal = Depends(require_local_fhir_launcher),
):
    configured_issuer = os.getenv("FHIR_PUBLIC_ISSUER", "").strip()
    if not configured_issuer:
        raise HTTPException(status_code=503, detail="FHIR public issuer is not configured")
    try:
        issuer = normalize_fhir_issuer(configured_issuer)
    except ValueError as error:
        raise HTTPException(
            status_code=503,
            detail="FHIR public issuer configuration is invalid",
        ) from error
    if payload.issuer != issuer:
        raise HTTPException(
            status_code=409,
            detail="SMART launch issuer does not match the configured FHIR issuer",
        )

    invitation = runtime.consultation_repository.create_invitation(
        institution_id=principal.institution_id,
        patient_sno=payload.patient_id,
        reg_sno=payload.encounter_id or f"smart-patient:{payload.patient_id}",
        prefill=payload.prefill.model_dump(exclude_none=True),
        actor_sub=principal.subject,
        ttl_seconds=_launcher_code_ttl_seconds(),
        fhir_context={
            "issuer": issuer,
            "patient_id": payload.patient_id,
            "encounter_id": payload.encounter_id,
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "invite_id": invitation["invite_id"],
        "code": invitation["token"],
        "expires_at": invitation["expires_at"],
        "status": invitation["status"],
    }


@router.post(
    "/invitations/exchange",
    response_model=InvitationExchangeResponse,
    responses=error_responses(400, 404, 409, 422),
    summary="Exchange an invitation token for an HttpOnly patient session",
)
def exchange_invitation(payload: InvitationExchangeRequest, response: Response):
    try:
        result = runtime.consultation_repository.exchange_invitation(payload.token)
    except ValueError as error:
        raise HTTPException(status_code=409, detail="Invitation has already been used") from error
    if result is None:
        raise HTTPException(status_code=404, detail="Invitation is invalid or expired")
    response.set_cookie(
        PATIENT_SESSION_COOKIE,
        result.pop("session_token"),
        max_age=8 * 60 * 60,
        secure=_secure_cookie(),
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {"status": "ok", "expires_at": result["expires_at"]}


@router.get(
    "/patient/session",
    response_model=PatientSessionResponse,
    responses=error_responses(401),
    summary="Restore the authenticated patient interview session",
)
def patient_session(request: Request, _: dict = Depends(require_patient_session)):
    session = request.state.patient_session
    audit_patient("patient.session.restore", "success", session)
    prefill = session.get("prefill") or {}
    fhir_context = session.get("fhir_context") or {}
    return {
        "status": "active",
        "expires_at": session["expires_at"],
        "interview_session_id": session["interview_session_id"],
        "patient_name": prefill.get("name"),
        "fhir_patient_id": fhir_context.get("patient_id"),
        "fhir_encounter_id": fhir_context.get("encounter_id"),
        "consultation_id": session.get("consultation_id"),
        "completed": bool(session.get("consultation_id")),
    }
