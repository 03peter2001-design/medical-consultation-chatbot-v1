"""Read models exposed by the clinician rule center."""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any, Callable

from amie.disease_profiles import (
    configured_safety_rule_routes,
)
from amie.rule_config import clinical_fact_descriptions
from domain.questionnaires import (
    load_questionnaire_category,
    load_questionnaire_policy,
)

from .common import revision

CATEGORY_ORDER = {
    "universal": 0,
    "chest": 1,
    "headache": 2,
    "abdomen": 3,
    "structured": 4,
}
FACT_CATEGORY_ORDER = {
    "safety": 0,
    "chest": 1,
    "headache": 2,
    "abdomen": 3,
    "common": 4,
}


def governance_profiles(document: dict[str, Any]) -> list[dict[str, Any]]:
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


def rule_groups(document: dict[str, Any]) -> list[dict[str, Any]]:
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
        add_rule(rule, kind="combination", scope="combination", route=rule["route"])
    for rule in document["structured_rules"]:
        add_rule(rule, kind="structured", scope="structured")
    groups = list(grouped.values())
    rule_routes = configured_safety_rule_routes()
    for group in groups:
        group["categories"].sort(key=lambda item: CATEGORY_ORDER.get(item, 99))
        applicable = [rule_routes[rule["code"]] for rule in group["rules"]]
        group["applicable_routes"] = sorted(
            set.intersection(*applicable) if applicable else set(),
            key=lambda item: CATEGORY_ORDER.get(item, 99),
        )
    return groups


def draft_rule_groups(
    document: dict[str, Any],
    current: dict[str, Any],
) -> list[dict[str, Any]]:
    """Keep deployed labels as stable identifiers while labels are edited."""
    original_by_code = {
        rule["code"]: group["original_label"]
        for group in rule_groups(current)
        for rule in group["rules"]
    }
    groups = rule_groups(document)
    for group in groups:
        originals = {original_by_code[rule["code"]] for rule in group["rules"]}
        if len(originals) != 1:
            raise ValueError("一個草稿標籤不可合併多個既有標籤")
        group["original_label"] = originals.pop()
    return groups


def fact_catalog(
    rules: dict[str, Any],
    *,
    load_profile_document: Callable[[str], dict[str, Any]],
) -> list[dict[str, Any]]:
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
                for key in ("findings", "negated_findings", "resolution_facts"):
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
                    key=lambda item: FACT_CATEGORY_ORDER.get(item, 99),
                ),
            }
        )
    return catalog


def rule_center_payload(
    rules: dict[str, Any],
    *,
    load_profile_document: Callable[[str], dict[str, Any]],
    read_profile_source: Callable[[str], dict[str, Any]],
    confirmation_text: str,
    fact_confirmation_text: str,
    disease_confirmation_text: str,
    max_clue_weight: int,
) -> dict[str, Any]:
    catalog = fact_catalog(rules, load_profile_document=load_profile_document)
    routes = []
    for route in rules["supported_routes"]:
        profile = read_profile_source(route)
        policy = load_questionnaire_policy(route)
        routes.append(
            {
                "route": route,
                "policy": policy,
                "profile_version": profile["profile_version"],
                "profile_revision": revision(profile),
                "profile_count": len(profile["profiles"]),
                "must_not_miss_count": sum(
                    bool(item["must_not_miss"]) for item in profile["profiles"]
                ),
                "provisional": any(
                    item["review_status"] == "provisional" for item in profile["profiles"]
                ),
                "sources": deepcopy(profile["sources"]),
                "profiles": governance_profiles(profile),
            }
        )
    return {
        "schema_version": rules["schema_version"],
        "revision": revision(rules),
        "edit_enabled": bool(os.getenv("SAFETY_RULE_ADMIN_TOKEN", "").strip()),
        "confirmation_text": confirmation_text,
        "fact_confirmation_text": fact_confirmation_text,
        "disease_confirmation_text": disease_confirmation_text,
        "max_clue_weight": max_clue_weight,
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
                "name": "標籤漏斗選題",
                "description": (
                    "先問 Safety 與必要問題，再依現有標籤建立動態領先群，"
                    "選擇最能區辨候選或確認領先疾病的未答問題。"
                ),
            },
        ],
        "routes": routes,
        "fact_count": len(catalog),
        "fact_codes": [item["code"] for item in catalog],
        "fact_catalog": catalog,
        "safety_groups": rule_groups(rules),
    }
