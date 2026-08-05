"""Validation and candidate construction for governed rule changes."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Callable

from amie.clinical_facts import FACT_CODES
from amie.disease_profiles import configured_safety_rule_codes, validate_profile_document
from amie.rule_config import validate_safety_rules

from .read_model import rule_groups

MAX_CLUE_WEIGHT = 10


def candidate_fact_labels(
    current: dict[str, Any],
    labels: Any,
    *,
    build_fact_catalog: Callable[[dict[str, Any]], list[dict[str, Any]]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    catalog = build_fact_catalog(current)
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


def nonempty_lines(value: Any, path: str, *, maximum: int = 80) -> list[str]:
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


def validate_edit_groups(
    current: dict[str, Any],
    groups: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, list[str]]]:
    if not isinstance(groups, list) or not groups:
        raise ValueError("safety_groups 必須是非空陣列")
    current_groups = rule_groups(current)
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
        candidates[label] = nonempty_lines(
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


def candidate_document(current: dict[str, Any], groups: Any) -> dict[str, Any]:
    incoming, labels_by_code, candidates = validate_edit_groups(current, groups)
    candidate = deepcopy(current)

    def update_rule(rule: dict[str, Any]) -> None:
        edited = incoming[rule["code"]]
        rule["label"] = labels_by_code[rule["code"]]
        kind = edited["kind"]
        if kind == "phrase":
            rule["terms"] = nonempty_lines(edited.get("terms"), f"{rule['code']}.terms")
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


def candidate_profile_document(
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
                or not 1 <= weight <= MAX_CLUE_WEIGHT
            ):
                raise ValueError(f"{path}.weight 必須介於 1 至 {MAX_CLUE_WEIGHT}")
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
