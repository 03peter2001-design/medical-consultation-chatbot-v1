"""Validated, auditable management of clinician-editable Safety rules."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from amie.clinical_facts import FACT_CODES
from amie.disease_profiles import (
    PROFILE_DATA_DIR,
    configured_safety_rule_codes,
    configured_safety_rule_routes,
    load_profile_document,
    validate_profile_document,
)
from amie.rule_config import (
    SAFETY_RULES_PATH,
    clinical_fact_descriptions,
    load_safety_rules,
    validate_safety_rules,
)
from domain.questionnaires import (
    load_questionnaire_category,
    load_questionnaire_policy,
)

AUDIT_DIR = SAFETY_RULES_PATH.parents[2] / "data" / "safety_rule_audit"
DISEASE_PROFILE_AUDIT_DIR = SAFETY_RULES_PATH.parents[2] / "data" / "disease_profile_audit"
_UPDATE_LOCK = threading.Lock()
_CONFIRMATION = "更新安全規則"
_FACT_CONFIRMATION = "更新標籤設定"
_DISEASE_CONFIRMATION = "更新疾病票數"
_MAX_CLUE_WEIGHT = 10
_CATEGORY_ORDER = {
    "universal": 0,
    "chest": 1,
    "headache": 2,
    "abdomen": 3,
    "structured": 4,
}
_FACT_CATEGORY_ORDER = {
    "safety": 0,
    "chest": 1,
    "headache": 2,
    "abdomen": 3,
    "common": 4,
}


def _revision(document: dict[str, Any]) -> str:
    canonical = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


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
        raise ValueError(
            f"疾病表 JSON 格式錯誤：{error.lineno}:{error.colno}",
        ) from error
    return validate_profile_document(document)


def _governance_profiles(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": profile["id"],
            "name": profile["name"],
            "must_not_miss": profile["must_not_miss"],
            "review_status": profile["review_status"],
            "reviewer": profile["reviewer"],
            "reviewed_at": profile["reviewed_at"],
            "safety_rule_codes": list(profile["safety_rule_codes"]),
            "clues": deepcopy(profile["clues"]),
        }
        for profile in document["profiles"]
    ]


def _rule_groups(document: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    def add_rule(
        rule: dict[str, Any],
        *,
        kind: str,
        scope: str,
        route: str = "",
    ) -> None:
        label = rule["label"]
        group = grouped.setdefault(
            label,
            {
                "original_label": label,
                "label": label,
                "possible_conditions": list(document["urgent_condition_candidates"].get(label, [])),
                "rules": [],
                "categories": [],
            },
        )
        category = (
            route
            if scope == "route" and route
            else "structured"
            if kind == "structured"
            else "universal"
        )
        if category not in group["categories"]:
            group["categories"].append(category)
        editable = {
            "code": rule["code"],
            "kind": kind,
            "scope": scope,
            "route": route,
            "level": rule.get("level", "urgent"),
        }
        if kind == "phrase":
            editable["terms"] = list(rule["terms"])
        elif kind == "combination":
            editable["all_term_groups"] = deepcopy(rule["all_term_groups"])
        else:
            editable["when"] = deepcopy(rule["when"])
        group["rules"].append(editable)

    raw = document["raw_rules"]
    for rule in raw["universal"]:
        add_rule(rule, kind="phrase", scope="universal")
    for route, rules in raw["routes"].items():
        for rule in rules:
            add_rule(rule, kind="phrase", scope="route", route=route)
    for rule in raw["combinations"]:
        add_rule(
            rule,
            kind="combination",
            scope="combination",
            route=rule["route"],
        )
    for rule in document["structured_rules"]:
        add_rule(rule, kind="structured", scope="structured")
    groups = list(grouped.values())
    rule_routes = configured_safety_rule_routes()
    for group in groups:
        group["categories"].sort(
            key=lambda item: _CATEGORY_ORDER.get(item, 99),
        )
        applicable = [rule_routes[rule["code"]] for rule in group["rules"]]
        group["applicable_routes"] = sorted(
            set.intersection(*applicable) if applicable else set(),
            key=lambda item: _CATEGORY_ORDER.get(item, 99),
        )
    return groups


def _draft_rule_groups(
    document: dict[str, Any],
    current: dict[str, Any],
) -> list[dict[str, Any]]:
    """Keep deployed labels as stable identifiers while labels are edited."""
    original_by_code = {
        rule["code"]: group["original_label"]
        for group in _rule_groups(current)
        for rule in group["rules"]
    }
    groups = _rule_groups(document)
    for group in groups:
        originals = {original_by_code[rule["code"]] for rule in group["rules"]}
        if len(originals) != 1:
            raise ValueError("一個草稿標籤不可合併多個既有標籤")
        group["original_label"] = originals.pop()
    return groups


def _require_admin_token(admin_token: str) -> None:
    configured_token = os.getenv("SAFETY_RULE_ADMIN_TOKEN", "").strip()
    if not configured_token:
        raise PermissionError("尚未設定 SAFETY_RULE_ADMIN_TOKEN，規則中心目前為唯讀")
    if not admin_token or not hmac.compare_digest(
        admin_token,
        configured_token,
    ):
        raise PermissionError("規則管理權杖不正確")


def authorize_rule_editor(admin_token: str) -> dict[str, bool]:
    """Verify the secret before exposing editing controls in the UI."""
    _require_admin_token(admin_token)
    return {"authorized": True}


def _fact_catalog(rules: dict[str, Any]) -> list[dict[str, Any]]:
    fact_codes = list(rules["finding_codes"])
    clinical_rules = rules["clinical_fact_rules"]
    for mapping in clinical_rules["scalar_mappings"].values():
        for code in mapping.values():
            if code not in fact_codes:
                fact_codes.append(code)
    for code in clinical_rules["symptom_mappings"].values():
        if code not in fact_codes:
            fact_codes.append(code)

    categories = {code: set() for code in fact_codes}
    conditional_safety_counts = {code: 0 for code in fact_codes}
    scalar_condition_fields = {
        "severity_in": "severity",
        "onset_in": "onset",
        "course_in": "course",
        "duration_in": "duration",
    }
    primary_fact_codes = {
        "chest": "symptom_chest_pain",
        "headache": "symptom_headache",
        "abdomen": "symptom_abdominal_pain",
    }
    for rule in rules["structured_rules"]:
        referenced_codes: set[str] = set()
        for key in ("any_findings", "all_findings"):
            for code in rule["when"].get(key, []):
                referenced_codes.add(code)
        for condition_key, field in scalar_condition_fields.items():
            mapping = clinical_rules["scalar_mappings"][field]
            for value in rule["when"].get(condition_key, []):
                if code := mapping.get(value):
                    referenced_codes.add(code)
        for route in rule["when"].get("primary_in", []):
            if code := primary_fact_codes.get(route):
                referenced_codes.add(code)
        for code in referenced_codes:
            conditional_safety_counts[code] += 1

    for route in rules["supported_routes"]:
        for question in load_questionnaire_category(route):
            for option in question.get("semantic_options", {}).values():
                for key in (
                    "findings",
                    "negated_findings",
                    "resolution_facts",
                ):
                    for code in option.get(key, []):
                        if code in categories:
                            categories[code].add(route)
        profile = load_profile_document(route)
        for disease in profile["profiles"]:
            for clue in disease["clues"]:
                code = clue["fact"]
                if code in categories:
                    categories[code].add(route)

    definitions = clinical_fact_descriptions(rules)
    symptom_definitions = rules["semantic_extraction"]["symptom_definitions"]
    for symptom, code in clinical_rules["symptom_mappings"].items():
        definition = symptom_definitions[symptom]
        route = definition.get("route")
        if route in rules["supported_routes"]:
            categories[code].add(route)

    direct_safety_codes = set(rules["safety_fact_codes"])
    for code in direct_safety_codes:
        categories[code].add("safety")

    catalog = []
    for code in fact_codes:
        assigned = categories[code] or {"common"}
        catalog.append(
            {
                "code": code,
                "description": definitions[code],
                "is_safety": code in direct_safety_codes,
                "conditional_safety_rule_count": conditional_safety_counts[code],
                "categories": sorted(
                    assigned,
                    key=lambda item: _FACT_CATEGORY_ORDER.get(item, 99),
                ),
            }
        )
    return catalog


def _candidate_fact_labels(
    current: dict[str, Any],
    labels: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    catalog = _fact_catalog(current)
    expected_codes = [item["code"] for item in catalog]
    if not isinstance(labels, list) or len(labels) != len(expected_codes):
        raise ValueError("ClinicalFact 標籤不可新增或刪除")

    incoming: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(labels):
        path = f"fact_labels[{index}]"
        if not isinstance(item, dict) or set(item) != {
            "code",
            "description",
            "is_safety",
        }:
            raise ValueError(f"{path} 只能包含 code、description 與 is_safety")
        code = item.get("code")
        description = item.get("description")
        is_safety = item.get("is_safety")
        if not isinstance(code, str) or code not in expected_codes or code in incoming:
            raise ValueError(f"{path}.code 不正確或重複")
        if (
            not isinstance(description, str)
            or not description.strip()
            or len(description.strip()) > 300
        ):
            raise ValueError(f"{path}.description 必須是 1 至 300 字")
        if not isinstance(is_safety, bool):
            raise ValueError(f"{path}.is_safety 必須是布林值")
        incoming[code] = {
            "description": description.strip(),
            "is_safety": is_safety,
        }
    if set(incoming) != set(expected_codes):
        raise ValueError("ClinicalFact 標籤不可新增或刪除")

    previous = {item["code"]: item for item in catalog}
    changes = [
        {
            "code": code,
            "previous_description": previous[code]["description"],
            "next_description": incoming[code]["description"],
            "previous_is_safety": previous[code]["is_safety"],
            "next_is_safety": incoming[code]["is_safety"],
        }
        for code in expected_codes
        if (
            previous[code]["description"] != incoming[code]["description"]
            or previous[code]["is_safety"] != incoming[code]["is_safety"]
        )
    ]
    candidate = deepcopy(current)
    semantic = candidate["semantic_extraction"]
    finding_codes = set(candidate["finding_codes"])
    for code, item in incoming.items():
        if code in finding_codes:
            semantic["finding_definitions"][code] = item["description"]
    for field, mapping in candidate["clinical_fact_rules"]["scalar_mappings"].items():
        definitions = semantic[f"{field}_definitions"]
        for value, code in mapping.items():
            definitions[value] = incoming[code]["description"]
    for symptom, code in candidate["clinical_fact_rules"]["symptom_mappings"].items():
        semantic["symptom_definitions"][symptom]["description"] = incoming[code]["description"]
    candidate["safety_fact_codes"] = [
        code for code in expected_codes if incoming[code]["is_safety"]
    ]
    return validate_safety_rules(candidate), changes


def rule_center_payload() -> dict[str, Any]:
    rules = load_safety_rules()
    fact_catalog = _fact_catalog(rules)
    routes = []
    for route in rules["supported_routes"]:
        profile = _read_profile_source(route)
        policy = load_questionnaire_policy(route)
        routes.append(
            {
                "route": route,
                "policy": policy,
                "profile_version": profile["profile_version"],
                "profile_revision": _revision(profile),
                "profile_count": len(profile["profiles"]),
                "must_not_miss_count": sum(
                    bool(item["must_not_miss"]) for item in profile["profiles"]
                ),
                "provisional": any(
                    item["review_status"] == "provisional" for item in profile["profiles"]
                ),
                "sources": deepcopy(profile["sources"]),
                "profiles": _governance_profiles(profile),
            }
        )
    return {
        "schema_version": rules["schema_version"],
        "revision": _revision(rules),
        "edit_enabled": bool(os.getenv("SAFETY_RULE_ADMIN_TOKEN", "").strip()),
        "confirmation_text": _CONFIRMATION,
        "fact_confirmation_text": _FACT_CONFIRMATION,
        "disease_confirmation_text": _DISEASE_CONFIRMATION,
        "max_clue_weight": _MAX_CLUE_WEIGHT,
        "flow": [
            {
                "step": 1,
                "name": "Safety 優先",
                "description": "直接 Safety 標籤、原文與組合規則先執行；命中即 urgent。",
            },
            {
                "step": 2,
                "name": "ClinicalFact 抽取",
                "description": "LLM 只能輸出白名單線索與逐字證據。",
            },
            {
                "step": 3,
                "name": "固定疾病表投票",
                "description": "程式計算支持票、反對票與完整度，不使用 RAG。",
            },
            {
                "step": 4,
                "name": "區辨力選題",
                "description": "先問安全必問題，再選能區分前五名的未答問題。",
            },
        ],
        "routes": routes,
        "fact_count": len(fact_catalog),
        "fact_codes": [item["code"] for item in fact_catalog],
        "fact_catalog": fact_catalog,
        "safety_groups": _rule_groups(rules),
    }


def _nonempty_lines(value: Any, path: str, *, maximum: int = 80) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > maximum
        or any(
            not isinstance(item, str) or not item.strip() or len(item.strip()) > 200
            for item in value
        )
    ):
        raise ValueError(f"{path} 必須是 1 至 {maximum} 個非空字串")
    return [item.strip() for item in value]


def _validate_edit_groups(
    current: dict[str, Any],
    groups: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, list[str]]]:
    if not isinstance(groups, list) or not groups:
        raise ValueError("safety_groups 必須是非空陣列")
    current_groups = _rule_groups(current)
    expected_labels = {group["original_label"] for group in current_groups}
    incoming_labels: set[str] = set()
    incoming_rules: dict[str, dict[str, Any]] = {}
    labels_by_code: dict[str, str] = {}
    candidates: dict[str, list[str]] = {}

    for index, group in enumerate(groups):
        path = f"safety_groups[{index}]"
        if not isinstance(group, dict):
            raise ValueError(f"{path} 必須是物件")
        original = str(group.get("original_label") or "").strip()
        label = str(group.get("label") or "").strip()
        if original not in expected_labels or original in incoming_labels:
            raise ValueError(f"{path}.original_label 不正確或重複")
        if not label or len(label) > 80:
            raise ValueError(f"{path}.label 必須是 1 至 80 字")
        if label in candidates:
            raise ValueError(f"更新後的 Safety 標籤重複：{label}")
        incoming_labels.add(original)
        candidates[label] = _nonempty_lines(
            group.get("possible_conditions"),
            f"{path}.possible_conditions",
        )
        rule_items = group.get("rules")
        if not isinstance(rule_items, list) or not rule_items:
            raise ValueError(f"{path}.rules 必須是非空陣列")
        for rule in rule_items:
            if not isinstance(rule, dict):
                raise ValueError(f"{path}.rules 含非物件")
            code = str(rule.get("code") or "").strip()
            if not code or code in incoming_rules:
                raise ValueError(f"{path}.rules 含空白或重複 code")
            incoming_rules[code] = rule
            labels_by_code[code] = label

    if incoming_labels != expected_labels:
        raise ValueError("Safety 標籤群組不可新增或刪除")
    expected_rules = {rule["code"]: rule for group in current_groups for rule in group["rules"]}
    if set(incoming_rules) != set(expected_rules):
        raise ValueError("Safety 規則 code 不可新增、刪除或變更")
    for code, incoming in incoming_rules.items():
        expected = expected_rules[code]
        for key in ("kind", "scope", "route", "level"):
            if incoming.get(key) != expected.get(key):
                raise ValueError(f"{code}.{key} 是唯讀欄位")
    return incoming_rules, labels_by_code, candidates


def _candidate_document(
    current: dict[str, Any],
    groups: Any,
) -> dict[str, Any]:
    incoming, labels_by_code, candidates = _validate_edit_groups(
        current,
        groups,
    )
    candidate = deepcopy(current)

    def update_rule(rule: dict[str, Any]) -> None:
        edited = incoming[rule["code"]]
        rule["label"] = labels_by_code[rule["code"]]
        kind = edited["kind"]
        if kind == "phrase":
            rule["terms"] = _nonempty_lines(
                edited.get("terms"),
                f"{rule['code']}.terms",
            )
        elif kind == "combination":
            raw_groups = edited.get("all_term_groups")
            if not isinstance(raw_groups, list) or len(raw_groups) < 2:
                raise ValueError(f"{rule['code']}.all_term_groups 至少需要兩組")
            rule["all_term_groups"] = deepcopy(raw_groups)
        else:
            when = edited.get("when")
            if not isinstance(when, dict) or not when:
                raise ValueError(f"{rule['code']}.when 必須是非空物件")
            rule["when"] = deepcopy(when)

    raw = candidate["raw_rules"]
    for rule in raw["universal"]:
        update_rule(rule)
    for rules in raw["routes"].values():
        for rule in rules:
            update_rule(rule)
    for rule in raw["combinations"]:
        update_rule(rule)
    for rule in candidate["structured_rules"]:
        update_rule(rule)
    candidate["urgent_condition_candidates"] = candidates
    return validate_safety_rules(candidate)


def _candidate_profile_document(
    current: dict[str, Any],
    profiles: Any,
    *,
    reviewer: str,
    reviewed_at: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    normalized_reviewer = reviewer.strip()
    if not 2 <= len(normalized_reviewer) <= 80:
        raise ValueError("審查醫師姓名必須介於 2 至 80 字")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("profiles 必須是非空陣列")

    current_by_id = {profile["id"]: profile for profile in current["profiles"]}
    incoming_by_id: dict[str, dict[str, Any]] = {}
    for index, profile in enumerate(profiles):
        path = f"profiles[{index}]"
        if not isinstance(profile, dict) or set(profile) != {
            "id",
            "clues",
            "safety_rule_codes",
        }:
            raise ValueError(f"{path} 只能包含 id、clues 與 safety_rule_codes")
        profile_id = str(profile.get("id") or "").strip()
        if profile_id not in current_by_id or profile_id in incoming_by_id:
            raise ValueError(f"{path}.id 不正確或重複")
        if not isinstance(profile.get("clues"), list):
            raise ValueError(f"{path}.clues 必須是陣列")
        safety_codes = profile.get("safety_rule_codes")
        if (
            not isinstance(safety_codes, list)
            or any(not isinstance(code, str) for code in safety_codes)
            or len(safety_codes) != len(set(safety_codes))
            or set(safety_codes) - configured_safety_rule_codes()
        ):
            raise ValueError(f"{path}.safety_rule_codes 含未知或重複規則")
        current_profile = current_by_id[profile_id]
        if current_profile["must_not_miss"] and not safety_codes:
            raise ValueError(f"{profile_id} 至少需要一條 Safety 觸發規則")
        if not current_profile["must_not_miss"] and safety_codes:
            raise ValueError(f"{profile_id} 非不能漏診疾病，不可綁定 Safety 規則")
        incoming_by_id[profile_id] = profile
    if set(incoming_by_id) != set(current_by_id):
        raise ValueError("疾病不可新增、刪除或遺漏")

    candidate = deepcopy(current)
    changes: list[dict[str, Any]] = []
    for profile in candidate["profiles"]:
        incoming = incoming_by_id[profile["id"]]
        current_clues = {clue["fact"]: clue for clue in profile["clues"]}
        incoming_clues: dict[str, dict[str, Any]] = {}
        for clue_index, clue in enumerate(incoming["clues"]):
            path = f"{profile['id']}.clues[{clue_index}]"
            if not isinstance(clue, dict) or set(clue) != {
                "fact",
                "status",
                "direction",
                "weight",
            }:
                raise ValueError(f"{path} 欄位不正確")
            fact = str(clue.get("fact") or "")
            if fact not in FACT_CODES or fact in incoming_clues:
                raise ValueError(f"{path}.fact 不在白名單或重複")
            if clue.get("status") not in {"present", "absent"}:
                raise ValueError(f"{path}.status 不正確")
            if clue.get("direction") not in {"support", "oppose"}:
                raise ValueError(f"{path}.direction 不正確")
            weight = clue.get("weight")
            if (
                not isinstance(weight, int)
                or isinstance(weight, bool)
                or not 1 <= weight <= _MAX_CLUE_WEIGHT
            ):
                raise ValueError(f"{path}.weight 必須介於 1 至 {_MAX_CLUE_WEIGHT}")
            incoming_clues[fact] = clue
        if not incoming_clues:
            raise ValueError(f"{profile['id']} 至少需要一個疾病標籤")

        profile_changes: list[dict[str, Any]] = []
        profile_source_ids = sorted(
            {source_id for clue in profile["clues"] for source_id in clue["source_ids"]}
        )
        next_clues = []
        for fact, incoming_clue in incoming_clues.items():
            current_clue = current_clues.get(fact)
            next_clue = {
                "fact": fact,
                "status": incoming_clue["status"],
                "direction": incoming_clue["direction"],
                "weight": incoming_clue["weight"],
                "source_ids": (
                    deepcopy(current_clue["source_ids"]) if current_clue else profile_source_ids
                ),
            }
            next_clues.append(next_clue)
            if current_clue is None:
                profile_changes.append(
                    {
                        "action": "added",
                        "profile_id": profile["id"],
                        "profile_name": profile["name"],
                        "fact": fact,
                        "previous": None,
                        "next": deepcopy(next_clue),
                    }
                )
            elif any(
                current_clue[key] != next_clue[key] for key in ("status", "direction", "weight")
            ):
                profile_changes.append(
                    {
                        "action": "updated",
                        "profile_id": profile["id"],
                        "profile_name": profile["name"],
                        "fact": fact,
                        "previous": deepcopy(current_clue),
                        "next": deepcopy(next_clue),
                    }
                )
        for fact, current_clue in current_clues.items():
            if fact not in incoming_clues:
                profile_changes.append(
                    {
                        "action": "removed",
                        "profile_id": profile["id"],
                        "profile_name": profile["name"],
                        "fact": fact,
                        "previous": deepcopy(current_clue),
                        "next": None,
                    }
                )

        safety_codes_changed = profile["safety_rule_codes"] != incoming["safety_rule_codes"]
        if profile_changes:
            profile["clues"] = next_clues
            changes.extend(profile_changes)
            for change in profile_changes:
                previous = change["previous"] or {}
                next_value = change["next"] or {}
                change["previous_weight"] = previous.get("weight")
                change["next_weight"] = next_value.get("weight")
        if safety_codes_changed:
            previous_codes = list(profile["safety_rule_codes"])
            profile["safety_rule_codes"] = list(incoming["safety_rule_codes"])
            changes.append(
                {
                    "action": "safety_triggers_updated",
                    "profile_id": profile["id"],
                    "profile_name": profile["name"],
                    "previous_rule_codes": previous_codes,
                    "next_rule_codes": list(profile["safety_rule_codes"]),
                }
            )
        if profile_changes or safety_codes_changed:
            profile["review_status"] = "reviewed"
            profile["reviewer"] = normalized_reviewer
            profile["reviewed_at"] = reviewed_at.isoformat(timespec="seconds")

    if not changes:
        raise ValueError("疾病標籤與票數沒有變更")
    timestamp_version = reviewed_at.strftime("%Y%m%d.%H%M%S.%f")
    candidate["profile_version"] = f"{candidate['route']}-governed-{timestamp_version}z"
    candidate["generation"] = {
        **candidate["generation"],
        "method": "clinician-governed-disease-rule-update",
        "model": "none",
        "generated_at": reviewed_at.isoformat(timespec="seconds"),
    }
    return validate_profile_document(candidate), changes


def _model_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("規則微調助理未回傳 JSON") from None
        try:
            payload = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as error:
            raise ValueError("規則微調助理回傳的 JSON 格式錯誤") from error
    if not isinstance(payload, dict):
        raise ValueError("規則微調助理回傳內容必須是物件")
    return payload


def suggest_safety_rule_edits(
    *,
    llm_client: Any,
    message: str,
    selected_labels: Any,
    groups: Any,
    history: Any,
) -> dict[str, Any]:
    """Return a validated draft; this function never persists rule changes."""
    normalized_message = message.strip()
    if not normalized_message or len(normalized_message) > 1000:
        raise ValueError("微調訊息必須是 1 至 1000 字")
    if (
        not isinstance(selected_labels, list)
        or not 1 <= len(selected_labels) <= 5
        or any(not isinstance(item, str) for item in selected_labels)
    ):
        raise ValueError("每次請勾選 1 至 5 個 Safety 標籤")

    current = load_safety_rules()
    draft = _candidate_document(current, groups)
    draft_groups = _draft_rule_groups(draft, current)
    by_original = {group["original_label"]: group for group in draft_groups}
    selected = list(dict.fromkeys(item.strip() for item in selected_labels))
    if len(selected) != len(selected_labels) or any(item not in by_original for item in selected):
        raise ValueError("勾選的 Safety 標籤不正確或重複")

    normalized_history = []
    if isinstance(history, list):
        for item in history[-6:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = str(item.get("content") or "").strip()[:1000]
            if role in {"user", "assistant"} and content:
                normalized_history.append(
                    {"role": role, "content": content},
                )

    selected_groups = [by_original[label] for label in selected]
    prompt_payload = {
        "request": normalized_message,
        "conversation": normalized_history,
        "allowed_fact_codes": current["finding_codes"],
        "selected_safety_groups": selected_groups,
    }
    response = llm_client.generate_text(
        [
            {
                "role": "system",
                "content": (
                    "你是醫師端 Safety JSON 編輯助理。你只能修改提供的既有群組，"
                    "不得新增、刪除或改寫 rule code、kind、scope、route、level，"
                    "不得使用 allowed_fact_codes 以外的 fact。請依醫師要求提出草稿，"
                    "不要宣稱已儲存。回傳 JSON："
                    '{"reply":"簡短說明","safety_groups":[完整群組物件]}。'
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    prompt_payload,
                    ensure_ascii=False,
                ),
            },
        ],
        temperature=0,
        max_tokens=4000,
    )
    payload = _model_json(response)
    reply = str(payload.get("reply") or "").strip()[:1000]
    suggestions = payload.get("safety_groups")
    if not reply or not isinstance(suggestions, list):
        raise ValueError("規則微調助理缺少 reply 或 safety_groups")

    suggested_by_original: dict[str, dict[str, Any]] = {}
    for item in suggestions:
        if not isinstance(item, dict):
            raise ValueError("規則微調助理的 safety_groups 含非物件")
        original = str(item.get("original_label") or "").strip()
        if original not in selected or original in suggested_by_original:
            raise ValueError("規則微調助理修改了未勾選或重複的標籤")
        suggested_by_original[original] = item
    if set(suggested_by_original) != set(selected):
        raise ValueError("規則微調助理未完整回傳所有勾選標籤")

    merged_groups = [
        suggested_by_original.get(group["original_label"], group) for group in draft_groups
    ]
    validated = _candidate_document(current, merged_groups)
    return {
        "reply": reply,
        "safety_groups": _draft_rule_groups(validated, current),
        "saved": False,
    }


def _atomic_write(path: Path, content: str) -> None:
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
    """Publish clinician-reviewed disease labels and weights with rollback."""
    _require_admin_token(admin_token)
    if confirmation.strip() != _DISEASE_CONFIRMATION:
        raise ValueError(f"請輸入「{_DISEASE_CONFIRMATION}」確認")
    normalized_note = change_note.strip()
    if len(normalized_note) < 4 or len(normalized_note) > 500:
        raise ValueError("變更理由必須介於 4 至 500 字")

    with _UPDATE_LOCK:
        path = _profile_source_path(route)
        current = _read_profile_source(route)
        current_revision = _revision(current)
        if expected_revision != current_revision:
            raise RuntimeError("疾病表已由其他人更新，請重新載入")

        timestamp = datetime.now(timezone.utc)
        candidate, changes = _candidate_profile_document(
            current,
            profiles,
            reviewer=reviewer,
            reviewed_at=timestamp,
        )
        next_revision = _revision(candidate)
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
        audit_path = DISEASE_PROFILE_AUDIT_DIR / (
            f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{route}-{current_revision[:12]}.json"
        )
        _atomic_write(
            audit_path,
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        )

        previous_content = json.dumps(current, ensure_ascii=False, indent=2) + "\n"
        next_content = json.dumps(candidate, ensure_ascii=False, indent=2) + "\n"
        try:
            _atomic_write(path, next_content)
            load_profile_document.cache_clear()
            loaded = _read_profile_source(route)
            if _revision(loaded) != next_revision:
                raise RuntimeError("疾病表更新後校驗失敗")
        except Exception:
            _atomic_write(path, previous_content)
            load_profile_document.cache_clear()
            _read_profile_source(route)
            raise
    return rule_center_payload()


def update_safety_rules(
    *,
    admin_token: str,
    expected_revision: str,
    confirmation: str,
    change_note: str,
    actor_session_id: str,
    groups: Any,
) -> dict[str, Any]:
    _require_admin_token(admin_token)
    if confirmation.strip() != _CONFIRMATION:
        raise ValueError(f"請輸入「{_CONFIRMATION}」確認")
    normalized_note = change_note.strip()
    if len(normalized_note) < 4 or len(normalized_note) > 500:
        raise ValueError("變更理由必須介於 4 至 500 字")

    with _UPDATE_LOCK:
        current = load_safety_rules()
        current_revision = _revision(current)
        if expected_revision != current_revision:
            raise RuntimeError("Safety 規則已由其他人更新，請重新載入")
        candidate = _candidate_document(current, groups)
        next_revision = _revision(candidate)
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
        audit_path = (
            AUDIT_DIR / f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{current_revision[:12]}.json"
        )
        _atomic_write(
            audit_path,
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        )

        previous_content = json.dumps(current, ensure_ascii=False, indent=2) + "\n"
        next_content = json.dumps(candidate, ensure_ascii=False, indent=2) + "\n"
        try:
            _atomic_write(SAFETY_RULES_PATH, next_content)
            load_safety_rules.cache_clear()
            load_profile_document.cache_clear()
            loaded = load_safety_rules()
            if _revision(loaded) != next_revision:
                raise RuntimeError("更新後規則校驗失敗")
        except Exception:
            _atomic_write(SAFETY_RULES_PATH, previous_content)
            load_safety_rules.cache_clear()
            load_profile_document.cache_clear()
            load_safety_rules()
            raise
    return rule_center_payload()


def update_fact_labels(
    *,
    admin_token: str,
    expected_revision: str,
    confirmation: str,
    change_note: str,
    actor_session_id: str,
    labels: Any,
) -> dict[str, Any]:
    _require_admin_token(admin_token)
    if confirmation.strip() != _FACT_CONFIRMATION:
        raise ValueError(f"請輸入「{_FACT_CONFIRMATION}」確認")
    normalized_note = change_note.strip()
    if len(normalized_note) < 4 or len(normalized_note) > 500:
        raise ValueError("變更理由必須介於 4 至 500 字")

    with _UPDATE_LOCK:
        current = load_safety_rules()
        current_revision = _revision(current)
        if expected_revision != current_revision:
            raise RuntimeError("ClinicalFact 標籤已由其他人更新，請重新載入")
        candidate, changes = _candidate_fact_labels(current, labels)
        if not changes:
            raise ValueError("ClinicalFact 標籤內容沒有變更")
        next_revision = _revision(candidate)

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
        audit_path = AUDIT_DIR / (
            f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-fact-labels-{current_revision[:12]}.json"
        )
        _atomic_write(
            audit_path,
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        )

        previous_content = json.dumps(current, ensure_ascii=False, indent=2) + "\n"
        next_content = json.dumps(candidate, ensure_ascii=False, indent=2) + "\n"
        try:
            _atomic_write(SAFETY_RULES_PATH, next_content)
            load_safety_rules.cache_clear()
            load_profile_document.cache_clear()
            loaded = load_safety_rules()
            if _revision(loaded) != next_revision:
                raise RuntimeError("ClinicalFact 標籤更新後校驗失敗")
        except Exception:
            _atomic_write(SAFETY_RULES_PATH, previous_content)
            load_safety_rules.cache_clear()
            load_profile_document.cache_clear()
            load_safety_rules()
            raise
    return rule_center_payload()
