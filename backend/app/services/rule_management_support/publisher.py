"""Audited publication workflows for clinician-governed rules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class PublisherRuntime:
    """Facade-owned dependencies, injected to preserve patchable service seams."""

    safety_rules_path: Path
    audit_dir: Path
    disease_profile_audit_dir: Path
    update_lock: Any
    require_admin_token: Callable[[str], None]
    atomic_write: Callable[[Path, str], None]
    revision: Callable[[dict[str, Any]], str]
    candidate_document: Callable[[dict[str, Any], Any], dict[str, Any]]
    candidate_fact_labels: Callable[
        [dict[str, Any], Any],
        tuple[dict[str, Any], list[dict[str, Any]]],
    ]
    candidate_profile_document: Any
    load_safety_rules: Any
    load_profile_document: Any
    profile_source_path: Callable[[str], Path]
    read_profile_source: Callable[[str], dict[str, Any]]
    rule_center_payload: Callable[[], dict[str, Any]]


def update_disease_profile(
    runtime: PublisherRuntime,
    *,
    route: str,
    admin_token: str,
    expected_revision: str,
    confirmation: str,
    confirmation_text: str,
    change_note: str,
    reviewer: str,
    actor_session_id: str,
    profiles: Any,
) -> dict[str, Any]:
    """Publish clinician-reviewed disease labels and weights with rollback."""
    runtime.require_admin_token(admin_token)
    if confirmation.strip() != confirmation_text:
        raise ValueError(f"請輸入「{confirmation_text}」確認")
    normalized_note = change_note.strip()
    if len(normalized_note) < 4 or len(normalized_note) > 500:
        raise ValueError("變更理由必須介於 4 至 500 字")

    with runtime.update_lock:
        path = runtime.profile_source_path(route)
        current = runtime.read_profile_source(route)
        current_revision = runtime.revision(current)
        if expected_revision != current_revision:
            raise RuntimeError("疾病表已由其他人更新，請重新載入")

        timestamp = datetime.now(timezone.utc)
        candidate, changes = runtime.candidate_profile_document(
            current,
            profiles,
            reviewer=reviewer,
            reviewed_at=timestamp,
        )
        next_revision = runtime.revision(candidate)
        audit = {
            "updated_at": timestamp.isoformat(timespec="seconds"),
            "actor_session_id": actor_session_id.strip()[:64],
            "reviewer": reviewer.strip(),
            "route": route,
            "change_note": normalized_note,
            "previous_revision": current_revision,
            "next_revision": next_revision,
            "changes": changes,
            "previous_document": current,
        }
        audit_path = runtime.disease_profile_audit_dir / (
            f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{route}-{current_revision[:12]}.json"
        )
        runtime.atomic_write(audit_path, json.dumps(audit, ensure_ascii=False, indent=2) + "\n")

        previous_content = json.dumps(current, ensure_ascii=False, indent=2) + "\n"
        next_content = json.dumps(candidate, ensure_ascii=False, indent=2) + "\n"
        try:
            runtime.atomic_write(path, next_content)
            runtime.load_profile_document.cache_clear()
            loaded = runtime.read_profile_source(route)
            if runtime.revision(loaded) != next_revision:
                raise RuntimeError("疾病表更新後校驗失敗")
        except Exception:
            runtime.atomic_write(path, previous_content)
            runtime.load_profile_document.cache_clear()
            runtime.read_profile_source(route)
            raise
    return runtime.rule_center_payload()


def update_safety_rules(
    runtime: PublisherRuntime,
    *,
    admin_token: str,
    expected_revision: str,
    confirmation: str,
    confirmation_text: str,
    change_note: str,
    actor_session_id: str,
    groups: Any,
) -> dict[str, Any]:
    runtime.require_admin_token(admin_token)
    if confirmation.strip() != confirmation_text:
        raise ValueError(f"請輸入「{confirmation_text}」確認")
    normalized_note = change_note.strip()
    if len(normalized_note) < 4 or len(normalized_note) > 500:
        raise ValueError("變更理由必須介於 4 至 500 字")

    with runtime.update_lock:
        current = runtime.load_safety_rules()
        current_revision = runtime.revision(current)
        if expected_revision != current_revision:
            raise RuntimeError("Safety 規則已由其他人更新，請重新載入")
        candidate = runtime.candidate_document(current, groups)
        next_revision = runtime.revision(candidate)
        if next_revision == current_revision:
            raise ValueError("規則內容沒有變更")

        timestamp = datetime.now(timezone.utc)
        audit = {
            "updated_at": timestamp.isoformat(timespec="seconds"),
            "actor_session_id": actor_session_id.strip()[:64],
            "change_note": normalized_note,
            "previous_revision": current_revision,
            "next_revision": next_revision,
            "previous_document": current,
        }
        audit_path = runtime.audit_dir / (
            f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{current_revision[:12]}.json"
        )
        runtime.atomic_write(audit_path, json.dumps(audit, ensure_ascii=False, indent=2) + "\n")

        previous_content = json.dumps(current, ensure_ascii=False, indent=2) + "\n"
        next_content = json.dumps(candidate, ensure_ascii=False, indent=2) + "\n"
        try:
            runtime.atomic_write(runtime.safety_rules_path, next_content)
            runtime.load_safety_rules.cache_clear()
            runtime.load_profile_document.cache_clear()
            loaded = runtime.load_safety_rules()
            if runtime.revision(loaded) != next_revision:
                raise RuntimeError("更新後規則校驗失敗")
        except Exception:
            runtime.atomic_write(runtime.safety_rules_path, previous_content)
            runtime.load_safety_rules.cache_clear()
            runtime.load_profile_document.cache_clear()
            runtime.load_safety_rules()
            raise
    return runtime.rule_center_payload()


def update_fact_labels(
    runtime: PublisherRuntime,
    *,
    admin_token: str,
    expected_revision: str,
    confirmation: str,
    confirmation_text: str,
    change_note: str,
    actor_session_id: str,
    labels: Any,
) -> dict[str, Any]:
    runtime.require_admin_token(admin_token)
    if confirmation.strip() != confirmation_text:
        raise ValueError(f"請輸入「{confirmation_text}」確認")
    normalized_note = change_note.strip()
    if len(normalized_note) < 4 or len(normalized_note) > 500:
        raise ValueError("變更理由必須介於 4 至 500 字")

    with runtime.update_lock:
        current = runtime.load_safety_rules()
        current_revision = runtime.revision(current)
        if expected_revision != current_revision:
            raise RuntimeError("ClinicalFact 標籤已由其他人更新，請重新載入")
        candidate, changes = runtime.candidate_fact_labels(current, labels)
        if not changes:
            raise ValueError("ClinicalFact 標籤內容沒有變更")
        next_revision = runtime.revision(candidate)

        timestamp = datetime.now(timezone.utc)
        audit = {
            "updated_at": timestamp.isoformat(timespec="seconds"),
            "event_type": "fact_labels_updated",
            "actor_session_id": actor_session_id.strip()[:64],
            "change_note": normalized_note,
            "previous_revision": current_revision,
            "next_revision": next_revision,
            "changes": changes,
            "previous_document": current,
        }
        audit_path = runtime.audit_dir / (
            f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-fact-labels-{current_revision[:12]}.json"
        )
        runtime.atomic_write(audit_path, json.dumps(audit, ensure_ascii=False, indent=2) + "\n")

        previous_content = json.dumps(current, ensure_ascii=False, indent=2) + "\n"
        next_content = json.dumps(candidate, ensure_ascii=False, indent=2) + "\n"
        try:
            runtime.atomic_write(runtime.safety_rules_path, next_content)
            runtime.load_safety_rules.cache_clear()
            runtime.load_profile_document.cache_clear()
            loaded = runtime.load_safety_rules()
            if runtime.revision(loaded) != next_revision:
                raise RuntimeError("ClinicalFact 標籤更新後校驗失敗")
        except Exception:
            runtime.atomic_write(runtime.safety_rules_path, previous_content)
            runtime.load_safety_rules.cache_clear()
            runtime.load_profile_document.cache_clear()
            runtime.load_safety_rules()
            raise
    return runtime.rule_center_payload()
