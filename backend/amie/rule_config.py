"""Load and validate versioned, data-driven AMIE safety rules."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

SAFETY_RULES_PATH = Path(__file__).resolve().parent / "rules" / "safety_rules.json"
_CONDITION_KEYS = {
    "primary_in",
    "severity_in",
    "onset_in",
    "course_in",
    "duration_in",
    "new_or_changed_in",
    "all_findings",
    "any_findings",
    "all_risks",
    "any_risks",
}
_VALUE_DOMAINS = {
    "severity_in": {"mild", "moderate", "severe", "unknown"},
    "onset_in": {"sudden", "gradual", "unknown"},
    "course_in": {"episodic", "continuous", "recurrent", "unknown"},
    "duration_in": {"brief", "prolonged", "unknown"},
    "new_or_changed_in": {"true", "false", "unknown"},
}


def _nonempty_strings(value: Any, path: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ValueError(f"{path} 必須是非空字串陣列")
    return value


def _validate_unique(values: list[str], path: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{path} 不可包含重複值")


def _validate_rule_identity(rule: Any, path: str) -> dict[str, Any]:
    if not isinstance(rule, dict):
        raise ValueError(f"{path} 必須是物件")
    for key in ("code", "label"):
        if not isinstance(rule.get(key), str) or not rule[key].strip():
            raise ValueError(f"{path}.{key} 必須是非空字串")
    if rule.get("level", "urgent") not in {"urgent", "routine"}:
        raise ValueError(f"{path}.level 只支援 urgent 或 routine")
    return rule


def _validate_urgent_condition_candidates(
    document: dict[str, Any],
    rule_labels: set[str],
) -> None:
    candidates = document.get("urgent_condition_candidates")
    if not isinstance(candidates, dict) or not candidates:
        raise ValueError("urgent_condition_candidates 必須是非空物件")
    for label, conditions in candidates.items():
        if not isinstance(label, str) or not label.strip():
            raise ValueError("urgent_condition_candidates 的 key 必須是非空字串")
        _validate_unique(
            _nonempty_strings(
                conditions,
                f"urgent_condition_candidates.{label}",
            ),
            f"urgent_condition_candidates.{label}",
        )
    missing = rule_labels - set(candidates)
    if missing:
        raise ValueError(f"urgent_condition_candidates 缺少安全規則標籤：{sorted(missing)}")


def _validate_phrase_rules(rules: Any, path: str) -> list[str]:
    if not isinstance(rules, list):
        raise ValueError(f"{path} 必須是陣列")
    codes = []
    for index, raw_rule in enumerate(rules):
        rule = _validate_rule_identity(raw_rule, f"{path}[{index}]")
        _nonempty_strings(rule.get("terms"), f"{path}[{index}].terms")
        codes.append(rule["code"])
    _validate_unique(codes, f"{path}.code")
    return codes


def _validate_clinical_fact_rules(
    document: dict[str, Any],
    finding_codes: set[str],
) -> set[str]:
    rules = document.get("clinical_fact_rules")
    if not isinstance(rules, dict):
        raise ValueError("clinical_fact_rules 必須是物件")
    record_fields = _nonempty_strings(
        rules.get("record_fields"),
        "clinical_fact_rules.record_fields",
    )
    if set(record_fields) != {
        "code",
        "status",
        "evidence",
        "source",
        "turn",
    }:
        raise ValueError("clinical_fact_rules.record_fields 格式不正確")
    statuses = _nonempty_strings(
        rules.get("statuses"),
        "clinical_fact_rules.statuses",
    )
    if set(statuses) != {"present", "absent"}:
        raise ValueError("clinical_fact_rules.statuses 格式不正確")

    scalar_mappings = rules.get("scalar_mappings")
    if not isinstance(scalar_mappings, dict) or not scalar_mappings:
        raise ValueError("clinical_fact_rules.scalar_mappings 必須是非空物件")
    scalar_codes: set[str] = set()
    for field, mapping in scalar_mappings.items():
        if (
            not isinstance(field, str)
            or not field.strip()
            or not isinstance(mapping, dict)
            or not mapping
        ):
            raise ValueError("clinical_fact_rules.scalar_mappings 格式不正確")
        for value, code in mapping.items():
            if (
                not isinstance(value, str)
                or not value.strip()
                or not isinstance(code, str)
                or not code.strip()
            ):
                raise ValueError(f"clinical_fact_rules.scalar_mappings.{field} 格式不正確")
            scalar_codes.add(code)
    symptom_mappings = rules.get("symptom_mappings")
    if not isinstance(symptom_mappings, dict) or not symptom_mappings:
        raise ValueError("clinical_fact_rules.symptom_mappings 必須是非空物件")
    symptom_codes: set[str] = set()
    for symptom, code in symptom_mappings.items():
        if (
            not isinstance(symptom, str)
            or not symptom.strip()
            or not isinstance(code, str)
            or not code.strip()
        ):
            raise ValueError("clinical_fact_rules.symptom_mappings 格式不正確")
        symptom_codes.add(code)
    fact_codes = finding_codes | scalar_codes | symptom_codes

    _validate_unique(
        _nonempty_strings(
            rules.get("legacy_text_fields"),
            "clinical_fact_rules.legacy_text_fields",
        ),
        "clinical_fact_rules.legacy_text_fields",
    )
    legacy_terms = rules.get("legacy_terms")
    if not isinstance(legacy_terms, dict):
        raise ValueError("clinical_fact_rules.legacy_terms 必須是物件")
    unknown_legacy_codes = set(legacy_terms) - fact_codes
    if unknown_legacy_codes:
        raise ValueError(
            f"clinical_fact_rules.legacy_terms 含未知 fact：{sorted(unknown_legacy_codes)}"
        )
    for code, terms in legacy_terms.items():
        _validate_unique(
            _nonempty_strings(
                terms,
                f"clinical_fact_rules.legacy_terms.{code}",
            ),
            f"clinical_fact_rules.legacy_terms.{code}",
        )

    field_rules = rules.get("legacy_field_rules")
    if not isinstance(field_rules, list):
        raise ValueError("clinical_fact_rules.legacy_field_rules 必須是陣列")
    for index, field_rule in enumerate(field_rules):
        path = f"clinical_fact_rules.legacy_field_rules[{index}]"
        if not isinstance(field_rule, dict) or set(field_rule) != {
            "field",
            "match",
            "values",
            "code",
            "status",
            "evidence",
        }:
            raise ValueError(f"{path} 格式不正確")
        if field_rule["match"] not in {"contains_any", "equals_any"}:
            raise ValueError(f"{path}.match 不正確")
        _nonempty_strings(field_rule["values"], f"{path}.values")
        if field_rule["code"] not in fact_codes:
            raise ValueError(f"{path}.code 含未知 fact")
        if field_rule["status"] not in statuses:
            raise ValueError(f"{path}.status 不正確")
        if not isinstance(field_rule["evidence"], str) or not field_rule["evidence"].strip():
            raise ValueError(f"{path}.evidence 必須是非空字串")
    return fact_codes


def _validate_disease_profile_rules(
    document: dict[str, Any],
    routes: set[str],
) -> None:
    rules = document.get("disease_profile_rules")
    if not isinstance(rules, dict) or set(rules) - routes:
        raise ValueError("disease_profile_rules 含未支援路由")
    safety_conditions = {
        condition
        for conditions in document["urgent_condition_candidates"].values()
        for condition in conditions
    }
    for route, route_rules in rules.items():
        path = f"disease_profile_rules.{route}"
        if not isinstance(route_rules, dict) or set(route_rules) != {
            "generation_query",
            "required_must_not_miss_profiles",
        }:
            raise ValueError(f"{path} 格式不正確")
        if (
            not isinstance(route_rules["generation_query"], str)
            or not route_rules["generation_query"].strip()
        ):
            raise ValueError(f"{path}.generation_query 必須是非空字串")
        profiles = route_rules["required_must_not_miss_profiles"]
        if not isinstance(profiles, dict) or not profiles:
            raise ValueError(f"{path}.required_must_not_miss_profiles 必須是非空物件")
        for profile_id, condition_names in profiles.items():
            if not isinstance(profile_id, str) or not profile_id.strip():
                raise ValueError(f"{path} 含空白 profile id")
            names = _nonempty_strings(
                condition_names,
                f"{path}.required_must_not_miss_profiles.{profile_id}",
            )
            if not set(names).issubset(safety_conditions):
                raise ValueError(f"{path}.{profile_id} 未對應 urgent_condition_candidates")


def validate_safety_rules(document: Any) -> dict[str, Any]:
    """Reject malformed rule files before any interview can use them."""
    if not isinstance(document, dict):
        raise ValueError("safety_rules.json 根節點必須是物件")
    if document.get("schema_version") != 2:
        raise ValueError("safety_rules.json schema_version 必須是 2")

    routes = _nonempty_strings(
        document.get("supported_routes"),
        "supported_routes",
    )
    _validate_unique(routes, "supported_routes")
    route_keywords = document.get("route_keywords")
    if not isinstance(route_keywords, dict):
        raise ValueError("route_keywords 必須是物件")
    if set(route_keywords) != set(routes):
        raise ValueError("route_keywords 必須完整對應 supported_routes")
    for route, keywords in route_keywords.items():
        _validate_unique(
            _nonempty_strings(keywords, f"route_keywords.{route}"),
            f"route_keywords.{route}",
        )
    findings = _nonempty_strings(
        document.get("finding_codes"),
        "finding_codes",
    )
    _validate_unique(findings, "finding_codes")
    fact_codes = _validate_clinical_fact_rules(document, set(findings))
    safety_fact_codes = document.get("safety_fact_codes")
    if (
        not isinstance(safety_fact_codes, list)
        or any(not isinstance(code, str) or code not in fact_codes for code in safety_fact_codes)
        or len(safety_fact_codes) != len(set(safety_fact_codes))
    ):
        raise ValueError("safety_fact_codes 必須是不重複的 ClinicalFact code 陣列")

    semantic = document.get("semantic_extraction")
    if not isinstance(semantic, dict):
        raise ValueError("semantic_extraction 必須是物件")
    _nonempty_strings(
        semantic.get("normalization_instructions"),
        "semantic_extraction.normalization_instructions",
    )
    severity_definitions = semantic.get("severity_definitions")
    expected_severity = {"mild", "moderate", "severe", "unknown"}
    if (
        not isinstance(severity_definitions, dict)
        or set(severity_definitions) != expected_severity
        or any(
            not isinstance(value, str) or not value.strip()
            for value in severity_definitions.values()
        )
    ):
        raise ValueError(
            "semantic_extraction.severity_definitions 必須完整定義 mild、moderate、severe、unknown"
        )
    for field, expected_values in (
        ("onset_definitions", {"sudden", "gradual", "unknown"}),
        (
            "course_definitions",
            {"episodic", "continuous", "recurrent", "unknown"},
        ),
        ("duration_definitions", {"brief", "prolonged", "unknown"}),
    ):
        definitions = semantic.get(field)
        if (
            not isinstance(definitions, dict)
            or set(definitions) != expected_values
            or any(
                not isinstance(value, str) or not value.strip() for value in definitions.values()
            )
        ):
            raise ValueError(f"semantic_extraction.{field} 定義不完整")
    symptom_definitions = semantic.get("symptom_definitions")
    symptom_mappings = document["clinical_fact_rules"]["symptom_mappings"]
    if not isinstance(symptom_definitions, dict) or set(symptom_definitions) != set(
        symptom_mappings
    ):
        raise ValueError("semantic_extraction.symptom_definitions 必須完整對應 symptom_mappings")
    for symptom, definition in symptom_definitions.items():
        if (
            not isinstance(definition, dict)
            or set(definition) != {"route", "description"}
            or definition["route"] not in routes
            or not isinstance(definition["description"], str)
            or not definition["description"].strip()
        ):
            raise ValueError(f"semantic_extraction.symptom_definitions.{symptom} 格式不正確")
    finding_definitions = semantic.get("finding_definitions")
    if (
        not isinstance(finding_definitions, dict)
        or set(finding_definitions) != set(findings)
        or any(
            not isinstance(value, str) or not value.strip()
            for value in finding_definitions.values()
        )
    ):
        raise ValueError("semantic_extraction.finding_definitions 必須完整對應 finding_codes")

    negation = document.get("negation")
    if not isinstance(negation, dict):
        raise ValueError("negation 必須是物件")
    _nonempty_strings(negation.get("terms"), "negation.terms")
    lookback = negation.get("lookback_chars")
    if not isinstance(lookback, int) or not 1 <= lookback <= 40:
        raise ValueError("negation.lookback_chars 必須介於 1 到 40")

    raw_rules = document.get("raw_rules")
    if not isinstance(raw_rules, dict):
        raise ValueError("raw_rules 必須是物件")
    all_raw_codes = _validate_phrase_rules(
        raw_rules.get("universal"),
        "raw_rules.universal",
    )
    route_rules = raw_rules.get("routes")
    if not isinstance(route_rules, dict):
        raise ValueError("raw_rules.routes 必須是物件")
    unknown_routes = set(route_rules) - set(routes)
    if unknown_routes:
        raise ValueError(f"raw_rules.routes 含未支援路由：{sorted(unknown_routes)}")
    for route, rules in route_rules.items():
        all_raw_codes.extend(_validate_phrase_rules(rules, f"raw_rules.routes.{route}"))

    combinations = raw_rules.get("combinations")
    if not isinstance(combinations, list):
        raise ValueError("raw_rules.combinations 必須是陣列")
    for index, raw_rule in enumerate(combinations):
        path = f"raw_rules.combinations[{index}]"
        rule = _validate_rule_identity(raw_rule, path)
        if rule.get("route") not in routes:
            raise ValueError(f"{path}.route 必須是支援的路由")
        groups = rule.get("all_term_groups")
        if not isinstance(groups, list) or len(groups) < 2:
            raise ValueError(f"{path}.all_term_groups 至少需要兩組")
        for group_index, group in enumerate(groups):
            group_path = f"{path}.all_term_groups[{group_index}]"
            if not isinstance(group, dict):
                raise ValueError(f"{group_path} 必須是物件")
            _nonempty_strings(group.get("terms"), f"{group_path}.terms")
        all_raw_codes.append(rule["code"])
    _validate_unique(all_raw_codes, "raw_rules 所有 code")

    history_fields = _nonempty_strings(
        document.get("fhir_history_fields"),
        "fhir_history_fields",
    )
    _validate_unique(history_fields, "fhir_history_fields")
    risk_patterns = document.get("fhir_risk_patterns")
    if not isinstance(risk_patterns, dict) or not risk_patterns:
        raise ValueError("fhir_risk_patterns 必須是非空物件")
    for risk, patterns in risk_patterns.items():
        if not isinstance(risk, str) or not risk.strip():
            raise ValueError("fhir_risk_patterns 的 key 必須是非空字串")
        for pattern in _nonempty_strings(
            patterns,
            f"fhir_risk_patterns.{risk}",
        ):
            try:
                re.compile(pattern, flags=re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"fhir_risk_patterns.{risk} 有無效正規表示式") from exc

    structured = document.get("structured_rules")
    if not isinstance(structured, list) or not structured:
        raise ValueError("structured_rules 必須是非空陣列")
    structured_codes = []
    route_domain = {*routes, "other", "unknown"}
    finding_domain = set(findings)
    risk_domain = set(risk_patterns)
    for index, raw_rule in enumerate(structured):
        path = f"structured_rules[{index}]"
        rule = _validate_rule_identity(raw_rule, path)
        structured_codes.append(rule["code"])
        when = rule.get("when")
        if not isinstance(when, dict) or not when:
            raise ValueError(f"{path}.when 必須是非空物件")
        unknown_keys = set(when) - _CONDITION_KEYS
        if unknown_keys:
            raise ValueError(f"{path}.when 有不支援條件：{unknown_keys}")
        for key, raw_values in when.items():
            values = _nonempty_strings(raw_values, f"{path}.when.{key}")
            if key == "primary_in":
                allowed = route_domain
            elif key in {"all_findings", "any_findings"}:
                allowed = finding_domain
            elif key in {"all_risks", "any_risks"}:
                allowed = risk_domain
            else:
                allowed = _VALUE_DOMAINS[key]
            invalid = set(values) - allowed
            if invalid:
                raise ValueError(f"{path}.when.{key} 含未定義值：{sorted(invalid)}")
    _validate_unique(structured_codes, "structured_rules.code")
    urgent_labels = {
        rule["label"]
        for rule in [
            *raw_rules["universal"],
            *(item for rules in route_rules.values() for item in rules),
            *combinations,
            *structured,
        ]
        if rule.get("level", "urgent") == "urgent"
    }
    _validate_urgent_condition_candidates(document, urgent_labels)
    _validate_disease_profile_rules(document, set(routes))
    return document


def read_safety_rules(path: Path = SAFETY_RULES_PATH) -> dict[str, Any]:
    """Read a rule file. This uncached entry point is useful for validation."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"找不到 safety 規則檔：{path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"safety 規則 JSON 格式錯誤：{path}:{exc.lineno}:{exc.colno}") from exc
    return validate_safety_rules(document)


@lru_cache(maxsize=1)
def load_safety_rules() -> dict[str, Any]:
    """Load and cache the deployed safety rule set."""
    return read_safety_rules()


def supported_routes() -> set[str]:
    return set(load_safety_rules()["supported_routes"])


def finding_codes() -> set[str]:
    return set(load_safety_rules()["finding_codes"])


def clinical_fact_rules() -> dict[str, Any]:
    return load_safety_rules()["clinical_fact_rules"]


def clinical_fact_codes() -> set[str]:
    rules = clinical_fact_rules()
    return {
        *finding_codes(),
        *(code for mapping in rules["scalar_mappings"].values() for code in mapping.values()),
        *rules["symptom_mappings"].values(),
    }


def clinical_fact_descriptions(
    document: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Resolve the editable description for every stable ClinicalFact code."""
    rules = document or load_safety_rules()
    semantic = rules["semantic_extraction"]
    descriptions = dict(semantic["finding_definitions"])
    clinical_rules = rules["clinical_fact_rules"]
    for field, mapping in clinical_rules["scalar_mappings"].items():
        definitions = semantic[f"{field}_definitions"]
        for value, code in mapping.items():
            descriptions[code] = definitions[value]
    for symptom, code in clinical_rules["symptom_mappings"].items():
        descriptions.setdefault(
            code,
            semantic["symptom_definitions"][symptom]["description"],
        )
    return descriptions


def disease_profile_rules(route: str) -> dict[str, Any]:
    rules = load_safety_rules()["disease_profile_rules"]
    if route not in rules:
        raise ValueError(f"找不到 {route} 疾病表規則")
    return rules[route]
