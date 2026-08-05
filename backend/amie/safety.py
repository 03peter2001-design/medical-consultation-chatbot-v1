"""Generic safety-rule engine backed by a versioned JSON policy."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .clinical_facts import facts_from_assessment
from .models import ChiefComplaintAssessment
from .rule_config import clinical_fact_descriptions, load_safety_rules


@dataclass(frozen=True)
class SafetyFlag:
    code: str
    label: str
    evidence: str
    level: str = "urgent"
    possible_conditions: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _affirmed(
    text: str,
    term: str,
    negation: dict[str, Any],
) -> bool:
    """Return true when a phrase occurs without configured nearby negation."""
    start = 0
    lookback = negation["lookback_chars"]
    while True:
        index = text.find(term, start)
        if index < 0:
            return False
        prefix = text[max(0, index - lookback) : index]
        if not any(item in prefix for item in negation["terms"]):
            return True
        start = index + len(term)


def _first_affirmed(
    text: str,
    terms: list[str],
    negation: dict[str, Any],
) -> str | None:
    return next(
        (term for term in terms if _affirmed(text, term, negation)),
        None,
    )


def _deduplicate(flags: list[SafetyFlag]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for flag in flags:
        if flag.code in seen:
            continue
        seen.add(flag.code)
        result.append(flag.as_dict())
    return result


def _phrase_flag(
    rule: dict[str, Any],
    text: str,
    negation: dict[str, Any],
    condition_candidates: dict[str, list[str]],
) -> SafetyFlag | None:
    evidence = _first_affirmed(text, rule["terms"], negation)
    if not evidence:
        return None
    return SafetyFlag(
        code=rule["code"],
        label=rule["label"],
        evidence=evidence,
        level=rule.get("level", "urgent"),
        possible_conditions=tuple(condition_candidates.get(rule["label"], [])),
    )


def detect_red_flags(
    route: str | None,
    answer: str,
    patient_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Evaluate configured raw-text rules without calling an LLM."""
    rules = load_safety_rules()
    clinical_values = " ".join(
        str(value)
        for key, value in patient_data.items()
        if key
        not in {
            "name",
            "birth_date",
            "national_id",
            "id_number",
            "patient_id",
            "_amie",
        }
    )
    text = f"{answer} {clinical_values}"
    negation = rules["negation"]
    raw_rules = rules["raw_rules"]
    condition_candidates = rules["urgent_condition_candidates"]
    flags: list[SafetyFlag] = []

    phrase_rules = [
        *raw_rules["universal"],
        *raw_rules["routes"].get(route or "", []),
    ]
    for rule in phrase_rules:
        if flag := _phrase_flag(
            rule,
            text,
            negation,
            condition_candidates,
        ):
            flags.append(flag)

    for rule in raw_rules["combinations"]:
        if rule["route"] != route:
            continue
        evidence = [
            _first_affirmed(text, group["terms"], negation) for group in rule["all_term_groups"]
        ]
        if all(evidence):
            flags.append(
                SafetyFlag(
                    code=rule["code"],
                    label=rule["label"],
                    evidence="、".join(item for item in evidence if item),
                    level=rule.get("level", "urgent"),
                    possible_conditions=tuple(condition_candidates.get(rule["label"], [])),
                )
            )
    return _deduplicate(flags)


def _structured_rule_evidence(
    when: dict[str, list[str]],
    assessment: ChiefComplaintAssessment,
    primary: str | None,
    present: dict[str, str],
    risk_profile: dict[str, dict[str, Any]],
) -> list[str] | None:
    """Return evidence when every configured predicate matches."""
    evidence: list[str] = []
    scalar_context = {
        "primary_in": (
            primary,
            assessment.primary_evidence if primary == assessment.primary_symptom else "",
        ),
        "severity_in": (
            assessment.severity.value,
            assessment.severity.evidence,
        ),
        "onset_in": (
            assessment.onset.value,
            assessment.onset.evidence,
        ),
        "course_in": (
            assessment.course.value,
            assessment.course.evidence,
        ),
        "duration_in": (
            assessment.duration.value,
            assessment.duration.evidence,
        ),
        "new_or_changed_in": (
            assessment.is_new_or_changed.value,
            assessment.is_new_or_changed.evidence,
        ),
    }
    for key, (value, value_evidence) in scalar_context.items():
        allowed = when.get(key)
        if allowed is None:
            continue
        if value not in allowed:
            return None
        if value_evidence:
            evidence.append(value_evidence)

    for key, require_all in (
        ("all_findings", True),
        ("any_findings", False),
    ):
        requested = when.get(key)
        if requested is None:
            continue
        matched = [present[code] for code in requested if code in present]
        if (require_all and len(matched) != len(requested)) or (not require_all and not matched):
            return None
        evidence.extend(matched)

    for key, require_all in (("all_risks", True), ("any_risks", False)):
        requested = when.get(key)
        if requested is None:
            continue
        matched = [
            risk_profile[risk] for risk in requested if risk_profile.get(risk, {}).get("present")
        ]
        if (require_all and len(matched) != len(requested)) or (not require_all and not matched):
            return None
        evidence.extend(
            str(item.get("evidence", "")).strip()
            for item in matched
            if str(item.get("evidence", "")).strip()
        )

    return list(dict.fromkeys(item for item in evidence if item))


def detect_structured_red_flags(
    assessment: ChiefComplaintAssessment,
    fhir_risk_profile: dict[str, dict[str, Any]] | None = None,
    route_hint: str | None = None,
) -> list[dict[str, Any]]:
    """Evaluate JSON policy against evidence-validated semantic facts."""
    rules = load_safety_rules()
    risk_profile = fhir_risk_profile or {}
    condition_candidates = rules["urgent_condition_candidates"]
    present = {
        finding.code: finding.evidence
        for finding in assessment.findings
        if finding.status == "present" and finding.evidence
    }
    supported = set(rules["supported_routes"])
    primary = (
        assessment.primary_symptom
        if assessment.primary_symptom in {*supported, "other"}
        else route_hint
    )

    flags: list[SafetyFlag] = []
    direct_safety_codes = set(rules["safety_fact_codes"])
    descriptions = clinical_fact_descriptions(rules)
    for fact in facts_from_assessment(
        assessment,
        turn=0,
        source="direct_safety_fact",
    ):
        if fact["status"] != "present" or fact["code"] not in direct_safety_codes:
            continue
        flags.append(
            SafetyFlag(
                code=f"clinical_fact:{fact['code']}",
                label=descriptions[fact["code"]],
                evidence=fact["evidence"],
            )
        )
    for rule in rules["structured_rules"]:
        evidence = _structured_rule_evidence(
            rule["when"],
            assessment,
            primary,
            present,
            risk_profile,
        )
        if evidence is None:
            continue
        flags.append(
            SafetyFlag(
                code=rule["code"],
                label=rule["label"],
                evidence="、".join(evidence),
                level=rule.get("level", "urgent"),
                possible_conditions=tuple(condition_candidates.get(rule["label"], [])),
            )
        )
    return _deduplicate(flags)
