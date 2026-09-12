"""Institution-scoped invitation lifecycle queries and atomic replacement."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any


def list_invitations(
    connection: sqlite3.Connection,
    institution_id: str,
    status: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    query = """
        WITH managed AS (
            SELECT i.invite_id, i.patient_sno, i.reg_sno,
                CASE WHEN i.consultation_id IS NOT NULL THEN 'completed'
                     WHEN i.status = 'active' AND i.expires_at <= ? THEN 'expired'
                     ELSE i.status END AS status,
                i.created_at, i.expires_at, i.consumed_at, i.consultation_id,
                i.replaced_by_invite_id,
                (SELECT MAX(ps.last_seen_at) FROM patient_sessions ps
                 WHERE ps.invite_id = i.invite_id) AS last_seen_at,
                (SELECT MAX(ps.expires_at) FROM patient_sessions ps
                 WHERE ps.invite_id = i.invite_id) AS session_expires_at
            FROM invitations i WHERE i.institution_id = ?
        )
    """
    parameters: list[Any] = [now, institution_id]
    where = ""
    if status is not None:
        where = " WHERE status = ?"
        parameters.append(status)
    # Keep count and page in the same read snapshot.
    connection.execute("BEGIN")
    total = connection.execute(
        query + "SELECT COUNT(*) FROM managed" + where, parameters
    ).fetchone()[0]
    rows = connection.execute(
        query
        + "SELECT * FROM managed"
        + where
        + " ORDER BY created_at DESC, invite_id DESC LIMIT ? OFFSET ?",
        [*parameters, limit, offset],
    ).fetchall()
    return {"items": [dict(row) for row in rows], "total": total}


def mutate_invitation(
    connection: sqlite3.Connection,
    institution_id: str,
    invite_id: str,
    actor_sub: str,
    reissue: bool,
) -> dict[str, str] | None:
    """Caller commits lifecycle mutation and its audit event together."""
    connection.execute("BEGIN IMMEDIATE")
    invitation = connection.execute(
        "SELECT * FROM invitations WHERE invite_id = ? AND institution_id = ?",
        (invite_id, institution_id),
    ).fetchone()
    if invitation is None:
        return None
    if invitation["consultation_id"]:
        raise ValueError("Completed invitations cannot be changed")
    if reissue and invitation["replaced_by_invite_id"]:
        raise ValueError("Invitation has already been reissued")
    if (
        reissue
        and connection.execute(
            """SELECT 1 FROM invitations WHERE institution_id = ? AND reg_sno = ?
           AND invite_id != ? AND status IN ('active', 'consumed') LIMIT 1""",
            (institution_id, invitation["reg_sno"], invite_id),
        ).fetchone()
    ):
        raise ValueError("Another invitation already exists for this encounter")
    now = datetime.now(timezone.utc)
    now_text = now.isoformat(timespec="milliseconds")
    connection.execute(
        "UPDATE invitations SET status = 'revoked' WHERE invite_id = ?", (invite_id,)
    )
    connection.execute(
        "UPDATE patient_sessions SET revoked_at = COALESCE(revoked_at, ?) WHERE invite_id = ?",
        (now_text, invite_id),
    )
    if not reissue:
        return {"status": "revoked"}
    token = secrets.token_urlsafe(32)
    replacement_id = secrets.token_hex(16)
    ttl = datetime.fromisoformat(invitation["expires_at"]) - datetime.fromisoformat(
        invitation["created_at"]
    )
    expires_at = (now + max(ttl, timedelta(seconds=1))).isoformat(timespec="milliseconds")
    connection.execute(
        """INSERT INTO invitations (
            invite_id, token_hash, institution_id, patient_sno, reg_sno,
            prefill_json, status, expires_at, created_by, created_at,
            fhir_issuer, fhir_patient_id, fhir_encounter_id
        ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)""",
        (
            replacement_id,
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
            institution_id,
            invitation["patient_sno"],
            invitation["reg_sno"],
            invitation["prefill_json"],
            expires_at,
            actor_sub,
            now_text,
            invitation["fhir_issuer"],
            invitation["fhir_patient_id"],
            invitation["fhir_encounter_id"],
        ),
    )
    connection.execute(
        "UPDATE invitations SET replaced_by_invite_id = ? WHERE invite_id = ?",
        (replacement_id, invite_id),
    )
    return {
        "invite_id": replacement_id,
        "token": token,
        "expires_at": expires_at,
        "status": "active",
    }
