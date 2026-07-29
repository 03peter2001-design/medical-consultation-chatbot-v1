"""Validated clinical facts shared by safety, scoring, and audit output."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .models import ChiefComplaintAssessment
from .rule_config import clinical_fact_codes, clinical_fact_rules

FACT_CODES = frozenset(clinical_fact_codes())


def normalize_fact(raw: Any) -> dict[str, Any] | None:
    """Return a bounded fact or reject values outside the deployed vocabulary."""
    rules = clinical_fact_rules()
    allowed_fields = set(rules["record_fields"])
    if not isinstance(raw, dict) or set(raw) != allowed_fields:
        return None
    code = str(raw.get("code", "")).strip()
    status = str(raw.get("status", "present")).strip().lower()
    evidence = str(raw.get("evidence", "")).strip()[:160]
    source = str(raw.get("source", "semantic")).strip()[:40] or "semantic"
    try:
        turn = max(0, int(raw.get("turn", 0)))
    except (TypeError, ValueError):
        turn = 0
    if code not in FACT_CODES or status not in set(rules["statuses"]) or not evidence:
        return None
    return {
        "code": code,
        "status": status,
        "evidence": evidence,
        "source": source,
        "turn": turn,
    }


def merge_facts(
    existing: Iterable[dict[str, Any]] | None,
    incoming: Iterable[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Merge facts deterministically; newer explicit evidence wins by code."""
    merged: dict[str, dict[str, Any]] = {}
    for raw in [*(existing or []), *(incoming or [])]:
        fact = normalize_fact(raw)
        if fact:
            merged[fact["code"]] = fact
    return [merged[code] for code in sorted(merged)]


def facts_from_assessment(
    assessment: ChiefComplaintAssessment,
    *,
    turn: int,
    source: str,
) -> list[dict[str, Any]]:
    """Convert the evidence-grounded semantic extraction into fact records."""
    facts: list[dict[str, Any]] = []
    scalar_codes = clinical_fact_rules()["scalar_mappings"]
    for field, mapping in scalar_codes.items():
        value = getattr(assessment, field)
        code = mapping.get(value.value)
        if code and value.evidence:
            facts.append(
                {
                    "code": code,
                    "status": "present",
                    "evidence": value.evidence,
                    "source": source,
                    "turn": turn,
                }
            )
    for finding in [*assessment.findings, *assessment.negated_findings]:
        facts.append(
            {
                "code": finding.code,
                "status": finding.status,
                "evidence": finding.evidence,
                "source": source,
                "turn": turn,
            }
        )
    return merge_facts([], facts)


def facts_from_legacy_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Reconstruct conservative facts from stored questionnaires without an LLM."""
    rules = clinical_fact_rules()
    text = "、".join(
        str(data.get(field, "")) for field in rules["legacy_text_fields"] if data.get(field)
    )
    facts = [
        {
            "code": code,
            "status": "present",
            "evidence": term,
            "source": "legacy_questionnaire",
            "turn": 0,
        }
        for code, terms in rules["legacy_terms"].items()
        for term in terms
        if term in text
    ]
    for field_rule in rules["legacy_field_rules"]:
        value = str(data.get(field_rule["field"], "")).strip()
        values = field_rule["values"]
        matched = (
            any(candidate in value for candidate in values)
            if field_rule["match"] == "contains_any"
            else value in values
        )
        if not matched:
            continue
        facts.append(
            {
                "code": field_rule["code"],
                "status": field_rule["status"],
                "evidence": (
                    value if field_rule["evidence"] == "$value" else field_rule["evidence"]
                ),
                "source": "legacy_questionnaire",
                "turn": 0,
            }
        )
    semantic = data.get("_semantic_safety_state") or data.get("_chief_assessment", {}).get(
        "extraction"
    )
    if semantic:
        try:
            assessment = ChiefComplaintAssessment.model_validate(semantic)
            facts.extend(
                facts_from_assessment(
                    assessment,
                    turn=0,
                    source="legacy_semantic",
                )
            )
        except Exception:
            pass
    return merge_facts(data.get("_clinical_facts", []), facts)
