"""UCC-created invitations and public patient session exchange."""

from __future__ import annotations

import os
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app import runtime
from app.contracts import (
    InvitationExchangeResponse,
    InvitationResponse,
    PatientSessionResponse,
    error_responses,
)
from app.models import InvitationCreateRequest, InvitationExchangeRequest
from app.security import (
    PATIENT_SESSION_COOKIE,
    UccPrincipal,
    require_patient_session,
    require_scopes,
)
from app.services.security_audit import audit_patient

router = APIRouter(tags=["patient"])


def _secure_cookie() -> bool:
    return os.getenv("PATIENT_COOKIE_SECURE", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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


@router.post(
    "/invitations",
    response_model=InvitationResponse,
    responses=error_responses(403, 422, 503),
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
    return {
        "status": "active",
        "expires_at": session["expires_at"],
        "interview_session_id": session["interview_session_id"],
        "consultation_id": session.get("consultation_id"),
        "completed": bool(session.get("consultation_id")),
    }
