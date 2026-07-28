"""Evidence-grounded semantic extraction for a free-text chief complaint."""

from __future__ import annotations

import json
import re
from typing import Any

from .models import (
    ChiefComplaintAssessment,
    ChiefFinding,
    EvidenceValue,
)
from .rule_config import finding_codes, load_safety_rules, supported_routes

_DIRECT_IDENTIFIER = re.compile(
    r"\b(?:[A-Z][12]\d{8}|\d{8,12})\b",
    flags=re.IGNORECASE,
)
_NORMALIZE_EVIDENCE = re.compile(r"[\s，,。.!！?？；;：:'\"「」『』、]+")


def _trim(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _normalized(value: str) -> str:
    return _NORMALIZE_EVIDENCE.sub("", value).lower()


def _evidence_occurrences(text: str, evidence: str) -> list[int]:
    normalized_text = _normalized(text)
    normalized_evidence = _normalized(evidence)
    if not normalized_evidence:
        return []
    starts = []
    offset = 0
    while True:
        index = normalized_text.find(normalized_evidence, offset)
        if index < 0:
            break
        starts.append(index)
        offset = index + max(len(normalized_evidence), 1)
    return starts


def _has_grounded_evidence(
    text: str,
    evidence: str,
    *,
    expected_absent: bool = False,
) -> bool:
    rules = load_safety_rules()
    negation_terms = rules["negation"]["terms"]
    lookback = rules["negation"]["lookback_chars"]
    normalized_text = _normalized(text)
    normalized_evidence = _normalized(evidence)
    for index in _evidence_occurrences(text, evidence):
        prefix = normalized_text[max(0, index - lookback) : index]
        negated = any(term in prefix for term in negation_terms)
        if negated == expected_absent:
            return True
    # An absent finding may quote the whole negated phrase, in which case
    # the configured negation term is inside the evidence itself.
    return bool(
        expected_absent
        and normalized_evidence
        and normalized_evidence in normalized_text
        and any(term in normalized_evidence for term in negation_terms)
    )


def _validated_evidence_value(
    text: str,
    item: EvidenceValue,
    allowed_values: set[str],
) -> EvidenceValue:
    value = _trim(item.value, 40).lower()
    evidence = _trim(item.evidence, 160)
    if (
        value not in allowed_values
        or value == "unknown"
        or not _has_grounded_evidence(text, evidence)
    ):
        return EvidenceValue(value="unknown", evidence="")
    return EvidenceValue(value=value, evidence=evidence)


def _validated_findings(
    text: str,
    findings: list[ChiefFinding],
    *,
    force_absent: bool = False,
) -> list[ChiefFinding]:
    validated: list[ChiefFinding] = []
    seen: set[tuple[str, str]] = set()
    allowed_findings = finding_codes()
    for finding in findings[:24]:
        status = "absent" if force_absent else finding.status
        if finding.code not in allowed_findings or status not in {"present", "absent"}:
            continue
        evidence = _trim(finding.evidence, 160)
        if not _has_grounded_evidence(
            text,
            evidence,
            expected_absent=status == "absent",
        ):
            continue
        key = (finding.code, status)
        if key in seen:
            continue
        seen.add(key)
        validated.append(
            ChiefFinding(
                code=finding.code,
                status=status,
                evidence=evidence,
            )
        )
    return validated


def validate_assessment(
    text: str,
    assessment: ChiefComplaintAssessment,
) -> ChiefComplaintAssessment:
    """Discard every model claim that is not grounded in the raw text."""
    allowed_routes = supported_routes()
    primary_evidence = _trim(assessment.primary_evidence, 160)
    primary_symptom = assessment.primary_symptom
    if primary_symptom not in {*allowed_routes, "other"} or not _has_grounded_evidence(
        text, primary_evidence
    ):
        primary_symptom = "unknown"
        primary_evidence = ""

    onset = _validated_evidence_value(
        text,
        assessment.onset,
        {"sudden", "gradual", "unknown"},
    )
    severity = _validated_evidence_value(
        text,
        assessment.severity,
        {"mild", "moderate", "severe", "unknown"},
    )
    is_new_or_changed = _validated_evidence_value(
        text,
        assessment.is_new_or_changed,
        {"true", "false", "unknown"},
    )
    findings = _validated_findings(text, assessment.findings)
    negated = _validated_findings(
        text,
        assessment.negated_findings,
        force_absent=True,
    )

    supported_domains = [
        route for route in assessment.symptom_domains if route in allowed_routes or route == "other"
    ]
    route_candidates = [
        route
        for route in assessment.route_candidates
        if route in allowed_routes or route == "other"
    ]
    if primary_symptom != "unknown" and primary_symptom not in route_candidates:
        route_candidates.insert(0, primary_symptom)

    return ChiefComplaintAssessment(
        primary_symptom=primary_symptom,
        primary_evidence=primary_evidence,
        symptom_domains=list(dict.fromkeys(supported_domains))[:4],
        onset=onset,
        severity=severity,
        is_new_or_changed=is_new_or_changed,
        findings=findings,
        negated_findings=negated,
        route_candidates=list(dict.fromkeys(route_candidates))[:4],
        uncertain_fields=[
            _trim(field, 80) for field in assessment.uncertain_fields[:12] if _trim(field, 80)
        ],
    )


def build_fhir_risk_profile(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalize selected historical risk factors without sending raw FHIR."""
    rules = load_safety_rules()
    history_fields = rules["fhir_history_fields"]
    history = "、".join(_trim(data.get(field), 500) for field in history_fields if data.get(field))
    profile: dict[str, dict[str, Any]] = {}
    for risk, patterns in rules["fhir_risk_patterns"].items():
        pattern = "|".join(f"(?:{item})" for item in patterns)
        match = re.search(pattern, history, flags=re.IGNORECASE)
        profile[risk] = {
            "present": bool(match),
            "evidence": match.group(0) if match else "",
        }
    return profile


class ChiefComplaintExtractor:
    """Use an LLM for semantic extraction while retaining deterministic control."""

    def __init__(self, llm_client: Any):
        self.llm = llm_client

    def extract(
        self,
        text: str,
    ) -> tuple[ChiefComplaintAssessment | None, str]:
        redacted = _DIRECT_IDENTIFIER.sub("[已遮蔽識別碼]", _trim(text, 1200))
        try:
            response = self.llm.generate_text(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是醫療預問診的主訴資訊抽取器，不是診斷或分流模型。"
                            "只能整理病人明確說出的內容。每個非unknown欄位都必須"
                            "附上病人原句中的逐字evidence，不得補充、推測或改寫。"
                            "只能輸出指定JSON，不得輸出診斷、建議或Markdown。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": self._prompt(redacted),
                    },
                ],
                temperature=0,
                max_tokens=900,
            )
            parsed = ChiefComplaintAssessment.from_model_text(response)
            return validate_assessment(redacted, parsed), ""
        except Exception as error:
            return None, f"{type(error).__name__}: {_trim(error, 240)}"

    @staticmethod
    def _prompt(text: str) -> str:
        rules = load_safety_rules()
        route_values = "、".join([*rules["supported_routes"], "other", "unknown"])
        finding_values = "、".join(rules["finding_codes"])
        example_finding = rules["finding_codes"][0]
        semantic = rules["semantic_extraction"]
        normalization_guidance = "\n".join(
            f"- {item}" for item in semantic["normalization_instructions"]
        )
        severity_guidance = json.dumps(
            semantic["severity_definitions"],
            ensure_ascii=False,
        )
        finding_guidance = json.dumps(
            semantic["finding_definitions"],
            ensure_ascii=False,
        )
        return f"""
請將以下病人自由主訴轉成結構化JSON。不要判斷urgent，不要診斷。

病人原文：
{text}

規則：
1. primary_symptom、symptom_domains及route_candidates只能是：
   {route_values}。
2. onset.value只能是sudden、gradual、unknown。
3. severity.value只能是mild、moderate、severe、unknown。
4. is_new_or_changed.value只能是true、false、unknown。
5. finding.code只能使用下列代碼：
   {finding_values}。
6. findings只放present；negated_findings只放病人明確否認的項目。
7. 每個非unknown值及finding都必須附原文逐字evidence。

語意正規化原則：
{normalization_guidance}

severity定義：
{severity_guidance}

finding定義：
{finding_guidance}

只回傳：
{{
  "primary_symptom": "unknown",
  "primary_evidence": "",
  "symptom_domains": [],
  "onset": {{"value": "unknown", "evidence": ""}},
  "severity": {{"value": "unknown", "evidence": ""}},
  "is_new_or_changed": {{"value": "unknown", "evidence": ""}},
  "findings": [
    {{"code": "{example_finding}", "status": "present", "evidence": "原文片段"}}
  ],
  "negated_findings": [],
  "route_candidates": [],
  "uncertain_fields": []
}}
""".strip()


def preferred_route(
    assessment: ChiefComplaintAssessment | None,
) -> str | None:
    if not assessment:
        return None
    allowed_routes = supported_routes()
    if assessment.primary_symptom in {*allowed_routes, "other"} and assessment.primary_evidence:
        return assessment.primary_symptom
    supported = [route for route in assessment.route_candidates if route in allowed_routes]
    return supported[0] if len(supported) == 1 else None
