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
    "new_or_changed_in",
    "all_findings",
    "any_findings",
    "all_risks",
    "any_risks",
}
_VALUE_DOMAINS = {
    "severity_in": {"mild", "moderate", "severe", "unknown"},
    "onset_in": {"sudden", "gradual", "unknown"},
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


def validate_safety_rules(document: Any) -> dict[str, Any]:
    """Reject malformed rule files before any interview can use them."""
    if not isinstance(document, dict):
        raise ValueError("safety_rules.json 根節點必須是物件")
    if document.get("schema_version") != 1:
        raise ValueError("safety_rules.json schema_version 必須是 1")

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
