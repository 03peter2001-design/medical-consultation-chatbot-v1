"""Stable facade for validated, auditable clinician rule management."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from amie.clinical_facts import FACT_CODES as FACT_CODES
from amie.disease_profiles import (
    PROFILE_DATA_DIR,
    load_profile_document,
    validate_profile_document,
)
from amie.rule_config import SAFETY_RULES_PATH, load_safety_rules

from .rule_management_support import assistant as _assistant
from .rule_management_support import common as _common
from .rule_management_support import publisher as _publisher
from .rule_management_support import read_model as _read_model
from .rule_management_support import validation as _validation

_atomic_write = _common.atomic_write
_candidate_document = _validation.candidate_document
_candidate_profile_document = _validation.candidate_profile_document
_draft_rule_groups = _read_model.draft_rule_groups
_model_json = _assistant.model_json
_nonempty_lines = _validation.nonempty_lines
_revision = _common.revision
_rule_groups = _read_model.rule_groups
_validate_edit_groups = _validation.validate_edit_groups
_MAX_CLUE_WEIGHT = _validation.MAX_CLUE_WEIGHT
_require_admin_token = _common.require_admin_token

AUDIT_DIR = SAFETY_RULES_PATH.parents[2] / "data" / "safety_rule_audit"
DISEASE_PROFILE_AUDIT_DIR = SAFETY_RULES_PATH.parents[2] / "data" / "disease_profile_audit"
_UPDATE_LOCK = threading.Lock()
_CONFIRMATION = "更新安全規則"
_FACT_CONFIRMATION = "更新標籤設定"
_DISEASE_CONFIRMATION = "更新疾病票數"


def _profile_source_path(route: str) -> Path:
    supported_routes = set(load_safety_rules()["supported_routes"])
    if route not in supported_routes:
        raise ValueError(f"不支援的疾病表路由：{route}")
    return PROFILE_DATA_DIR / f"{route}.json"


def _read_profile_source(route: str) -> dict[str, Any]:
    path = _profile_source_path(route)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"疾病表 JSON 格式錯誤：{error.lineno}:{error.colno}") from error
    return validate_profile_document(document)


def authorize_rule_editor(admin_token: str) -> dict[str, bool]:
    """Verify the secret before exposing editing controls in the UI."""
    _require_admin_token(admin_token)
    return {"authorized": True}


def _fact_catalog(rules: dict[str, Any]) -> list[dict[str, Any]]:
    return _read_model.fact_catalog(
        rules,
        load_profile_document=load_profile_document,
    )


def _candidate_fact_labels(
    current: dict[str, Any],
    labels: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return _validation.candidate_fact_labels(
        current,
        labels,
        build_fact_catalog=_fact_catalog,
    )


def rule_center_payload() -> dict[str, Any]:
    return _read_model.rule_center_payload(
        load_safety_rules(),
        load_profile_document=load_profile_document,
        read_profile_source=_read_profile_source,
        confirmation_text=_CONFIRMATION,
        fact_confirmation_text=_FACT_CONFIRMATION,
        disease_confirmation_text=_DISEASE_CONFIRMATION,
        max_clue_weight=_MAX_CLUE_WEIGHT,
    )


def suggest_safety_rule_edits(
    *,
    llm_client: Any,
    message: str,
    selected_labels: Any,
    groups: Any,
    history: Any,
) -> dict[str, Any]:
    return _assistant.suggest_safety_rule_edits(
        current=load_safety_rules(),
        llm_client=llm_client,
        message=message,
        selected_labels=selected_labels,
        groups=groups,
        history=history,
    )


def _publisher_runtime() -> _publisher.PublisherRuntime:
    return _publisher.PublisherRuntime(
        safety_rules_path=SAFETY_RULES_PATH,
        audit_dir=AUDIT_DIR,
        disease_profile_audit_dir=DISEASE_PROFILE_AUDIT_DIR,
        update_lock=_UPDATE_LOCK,
        require_admin_token=_require_admin_token,
        atomic_write=_atomic_write,
        revision=_revision,
        candidate_document=_candidate_document,
        candidate_fact_labels=_candidate_fact_labels,
        candidate_profile_document=_candidate_profile_document,
        load_safety_rules=load_safety_rules,
        load_profile_document=load_profile_document,
        profile_source_path=_profile_source_path,
        read_profile_source=_read_profile_source,
        rule_center_payload=rule_center_payload,
    )


def update_disease_profile(
    *,
    route: str,
    admin_token: str,
    expected_revision: str,
    confirmation: str,
    change_note: str,
    reviewer: str,
    actor_session_id: str,
    profiles: Any,
) -> dict[str, Any]:
    return _publisher.update_disease_profile(
        _publisher_runtime(),
        route=route,
        admin_token=admin_token,
        expected_revision=expected_revision,
        confirmation=confirmation,
        confirmation_text=_DISEASE_CONFIRMATION,
        change_note=change_note,
        reviewer=reviewer,
        actor_session_id=actor_session_id,
        profiles=profiles,
    )


def update_safety_rules(
    *,
    admin_token: str,
    expected_revision: str,
    confirmation: str,
    change_note: str,
    actor_session_id: str,
    groups: Any,
) -> dict[str, Any]:
    return _publisher.update_safety_rules(
        _publisher_runtime(),
        admin_token=admin_token,
        expected_revision=expected_revision,
        confirmation=confirmation,
        confirmation_text=_CONFIRMATION,
        change_note=change_note,
        actor_session_id=actor_session_id,
        groups=groups,
    )


def update_fact_labels(
    *,
    admin_token: str,
    expected_revision: str,
    confirmation: str,
    change_note: str,
    actor_session_id: str,
    labels: Any,
) -> dict[str, Any]:
    return _publisher.update_fact_labels(
        _publisher_runtime(),
        admin_token=admin_token,
        expected_revision=expected_revision,
        confirmation=confirmation,
        confirmation_text=_FACT_CONFIRMATION,
        change_note=change_note,
        actor_session_id=actor_session_id,
        labels=labels,
    )
