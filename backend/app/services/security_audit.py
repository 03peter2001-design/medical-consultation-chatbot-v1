"""Minimal, PII-safe security audit and operational logging helpers."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

_LOGGER = logging.getLogger("medical_consultation.security")
_EVENT_PATTERN = re.compile(r"[^a-z0-9_.:-]+")
_OUTCOMES = {"success", "denied", "failure"}


def opaque_id(namespace: str, value: Any) -> str:
    """Return a stable, non-reversible identifier suitable for audit rows."""
    normalized_namespace = _EVENT_PATTERN.sub("_", str(namespace).casefold())[:30] or "id"
    raw = str(value or "").encode("utf-8", errors="replace")
    digest = hashlib.sha256(normalized_namespace.encode("ascii") + b"\0" + raw).hexdigest()[:24]
    return f"{normalized_namespace}:{digest}"


def safe_log(
    action: str,
    outcome: str,
    *,
    error: BaseException | None = None,
    failure_stage: str | None = None,
) -> None:
    """Log whitelist-safe operational metadata; never log values or tracebacks."""
    normalized_action = _EVENT_PATTERN.sub("_", action.casefold())[:100] or "unknown"
    normalized_outcome = outcome if outcome in _OUTCOMES else "failure"
    error_type = type(error).__name__ if error is not None else "none"
    log = _LOGGER.info if normalized_outcome == "success" else _LOGGER.warning
    if failure_stage:
        normalized_stage = _EVENT_PATTERN.sub("_", failure_stage.casefold())[:60] or "unknown"
        log(
            "security_event action=%s outcome=%s error_type=%s failure_stage=%s",
            normalized_action,
            normalized_outcome,
            error_type,
            normalized_stage,
        )
    else:
        log(
            "security_event action=%s outcome=%s error_type=%s",
            normalized_action,
            normalized_outcome,
            error_type,
        )


def audit_event(
    action: str,
    outcome: str,
    *,
    actor_type: str,
    actor_id: str,
    institution_id: str | None = None,
    resource_type: str = "none",
    resource_id: str = "none",
) -> None:
    """Write a whitelist-only event without accepting details or request data."""
    from app import runtime

    try:
        runtime.consultation_repository.record_audit_event(
            actor_type=_EVENT_PATTERN.sub("_", actor_type.casefold())[:40] or "unknown",
            actor_id=str(actor_id)[:200] or "unknown",
            action=_EVENT_PATTERN.sub("_", action.casefold())[:100] or "unknown",
            resource_type=_EVENT_PATTERN.sub("_", resource_type.casefold())[:60] or "none",
            resource_id=str(resource_id)[:200] or "none",
            institution_id=(str(institution_id)[:100] if institution_id else None),
            outcome=outcome if outcome in _OUTCOMES else "failure",
        )
    except Exception as error:  # Audit failure must not alter API authorization semantics.
        safe_log("audit.persist", "failure", error=error)


def audit_ucc(
    action: str,
    outcome: str,
    principal: Any,
    *,
    resource_type: str = "none",
    resource_id: Any = "none",
) -> None:
    audit_event(
        action,
        outcome,
        actor_type="ucc_user",
        actor_id=str(principal.subject),
        institution_id=str(principal.institution_id),
        resource_type=resource_type,
        resource_id=opaque_id(resource_type, resource_id),
    )


def audit_patient(
    action: str,
    outcome: str,
    session: dict[str, Any],
    *,
    resource_type: str = "patient_session",
    resource_id: Any | None = None,
) -> None:
    session_id = str(session.get("session_id") or "unknown")
    audit_event(
        action,
        outcome,
        actor_type="patient",
        actor_id=opaque_id("patient_session", session_id),
        institution_id=str(session.get("institution_id") or "") or None,
        resource_type=resource_type,
        resource_id=opaque_id(resource_type, resource_id or session_id),
    )
