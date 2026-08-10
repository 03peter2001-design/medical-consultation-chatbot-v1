"""Authentication dependencies for UCC clinicians and external patients."""

from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Callable

import jwt
from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from app.services.security_audit import audit_event, opaque_id

PATIENT_SESSION_COOKIE = os.getenv("PATIENT_SESSION_COOKIE", "ai_patient_session")
_bearer = HTTPBearer(auto_error=False)
_patient_session_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "patient_session",
    default=None,
)
_ucc_principal_context: ContextVar[UccPrincipal | None]


@dataclass(frozen=True)
class UccPrincipal:
    subject: str
    institution_id: str
    scopes: frozenset[str]
    claims: dict[str, Any]


_ucc_principal_context = ContextVar("ucc_principal", default=None)

_LOCAL_DEVELOPMENT_SCOPES = frozenset(
    {
        "consultation:read",
        "consultation:delete",
        "consultation:chat",
        "rules:read",
        "rules:write",
        "invite:create",
    }
)


def _allow_local_auth_bypass(request: Request) -> bool:
    enabled = os.getenv("ALLOW_LOCAL_AUTH_BYPASS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    client = request.client
    if not enabled or client is None:
        return False
    try:
        return ip_address(client.host).is_loopback
    except ValueError:
        return False


def _build_local_development_principal() -> UccPrincipal:
    institution_id = os.getenv(
        "LOCAL_DEVELOPMENT_INSTITUTION",
        "local-development",
    ).strip() or "local-development"
    return UccPrincipal(
        subject="local-developer",
        institution_id=institution_id,
        scopes=_LOCAL_DEVELOPMENT_SCOPES,
        claims={
            "local_auth_bypass": True,
            "legacy_frontend_bypass": True,
        },
    )


def _local_development_principal(request: Request) -> UccPrincipal | None:
    if not _allow_local_auth_bypass(request):
        return None
    return _build_local_development_principal()


def _public_key() -> str:
    inline = os.getenv("UCC_JWT_PUBLIC_KEY", "").strip()
    if inline:
        return inline.replace("\\n", "\n")
    path = os.getenv("UCC_JWT_PUBLIC_KEY_PATH", "").strip()
    if path:
        try:
            return Path(path).read_text(encoding="utf-8")
        except OSError as error:
            raise HTTPException(status_code=503, detail="UCC JWT public key is unavailable") from error
    raise HTTPException(status_code=503, detail="UCC JWT verification is not configured")


def _claim_scopes(claims: dict[str, Any]) -> frozenset[str]:
    collected: set[str] = set()
    for raw in (claims.get("scope"), claims.get("scopes")):
        if isinstance(raw, str):
            collected.update(item for item in raw.split() if item)
        elif isinstance(raw, list):
            collected.update(str(item).strip() for item in raw if str(item).strip())
    return frozenset(collected)


def authenticate_ucc(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> UccPrincipal:
    local_principal = _local_development_principal(request)
    if local_principal is not None:
        request.state.ucc_principal = local_principal
        return local_principal
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    issuer = os.getenv("UCC_JWT_ISSUER", "ucc-ehis").strip()
    audience = os.getenv("UCC_JWT_AUDIENCE", "medical-consultation-api").strip()
    try:
        claims = jwt.decode(
            credentials.credentials,
            _public_key(),
            algorithms=["RS256"],
            issuer=issuer,
            audience=audience,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "jti"]},
        )
    except InvalidTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired UCC token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    institution_id = str(claims.get("institution_id") or claims.get("institution") or "").strip()
    if not institution_id:
        raise HTTPException(status_code=403, detail="UCC token has no institution context")
    principal = UccPrincipal(
        subject=str(claims["sub"])[:200],
        institution_id=institution_id[:100],
        scopes=_claim_scopes(claims),
        claims=claims,
    )
    request.state.ucc_principal = principal
    _ucc_principal_context.set(principal)
    return principal


def require_scopes(*required: str) -> Callable[..., UccPrincipal]:
    def dependency(principal: UccPrincipal = Depends(authenticate_ucc)) -> UccPrincipal:
        missing = set(required) - principal.scopes
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"Missing required scope: {', '.join(sorted(missing))}",
            )
        return principal

    return dependency


def _allow_local_anonymous_patient(request: Request) -> bool:
    enabled = os.getenv("ALLOW_LOCAL_ANONYMOUS_PATIENT", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    client = request.client
    if _allow_local_auth_bypass(request):
        return True
    if not enabled or client is None:
        return False
    try:
        return ip_address(client.host).is_loopback
    except ValueError:
        return False


async def require_patient_session(
    request: Request,
    session_token: str | None = Cookie(default=None, alias=PATIENT_SESSION_COOKIE),
):
    from app import runtime

    path_actions = {
        "/v1/patient/session": "patient.session.restore",
        "/v1/chat": "patient.chat",
        "/v1/transcribe": "patient.transcribe",
        "/v1/avatar/status": "patient.avatar.status",
        "/v1/avatar/warmup": "patient.avatar.warmup",
        "/v1/avatar/speak": "patient.avatar.speak",
    }
    action = path_actions.get(request.url.path, "patient.session.authenticate")
    if not session_token:
        if _allow_local_anonymous_patient(request):
            audit_event(
                action,
                "allowed",
                actor_type="development",
                actor_id="loopback",
                resource_type="patient_session",
                resource_id="local-anonymous",
            )
            context_token = _patient_session_context.set(None)
            try:
                yield None
            finally:
                _patient_session_context.reset(context_token)
            return
        audit_event(
            action,
            "denied",
            actor_type="anonymous",
            actor_id="missing",
            resource_type="patient_session",
            resource_id="missing",
        )
        raise HTTPException(status_code=401, detail="Patient session required")
    session = runtime.consultation_repository.get_patient_session(session_token)
    if session is None:
        fingerprint = opaque_id("patient_session_token", session_token)
        audit_event(
            action,
            "denied",
            actor_type="anonymous",
            actor_id=fingerprint,
            resource_type="patient_session",
            resource_id=fingerprint,
        )
        raise HTTPException(status_code=401, detail="Patient session is invalid or expired")
    request.state.patient_session = session
    context_token = _patient_session_context.set(session)
    try:
        yield session
    finally:
        _patient_session_context.reset(context_token)


def current_patient_session() -> dict[str, Any] | None:
    """Return the session installed by the HTTP dependency, if any."""

    return _patient_session_context.get()


def current_ucc_principal() -> UccPrincipal | None:
    principal = _ucc_principal_context.get()
    if principal is not None:
        return principal
    enabled = os.getenv("ALLOW_LOCAL_AUTH_BYPASS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return _build_local_development_principal() if enabled else None
