"""Shared rule-management primitives without application-service dependencies."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from pathlib import Path
from typing import Any

INTERNAL_RULE_AUTHORIZATION = "__ucc_jwt_scope_authorized__"


def revision(document: dict[str, Any]) -> str:
    canonical = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def require_admin_token(admin_token: str) -> None:
    if hmac.compare_digest(admin_token, INTERNAL_RULE_AUTHORIZATION):
        return
    configured_token = os.getenv("SAFETY_RULE_ADMIN_TOKEN", "").strip()
    if not configured_token:
        raise PermissionError("尚未設定 SAFETY_RULE_ADMIN_TOKEN，規則中心目前為唯讀")
    if not admin_token or not hmac.compare_digest(admin_token, configured_token):
        raise PermissionError("規則管理權杖不正確")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
