"""Evidence-grounded semantic extraction for a free-text chief complaint."""

from __future__ import annotations

import json
import re
from typing import Any, cast

from .models import (
    ChiefComplaintAssessment,
    ChiefFinding,
    EvidenceValue,
    RouteEvidence,
    SymptomAssessment,
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


def _validated_routes(
    text: str,
    routes: list[str | RouteEvidence],
    allowed_routes: set[str],
) -> list[str]:
    validated: list[str] = []
    for item in routes[:12]:
        if isinstance(item, RouteEvidence):
            route = _trim(item.route, 40).lower()
            evidence = _trim(item.evidence, 160)
            if not _has_grounded_evidence(text, evidence):
                continue
        else:
            route = _trim(item, 40).lower()
        if route not in allowed_routes and route != "other":
            continue
        if route not in validated:
            validated.append(route)
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

    supported_domains = _validated_routes(
        text,
        assessment.symptom_domains,
        allowed_routes,
    )
    route_candidates = _validated_routes(
        text,
        assessment.route_candidates,
        allowed_routes,
    )
    if primary_symptom != "unknown" and primary_symptom not in route_candidates:
        route_candidates.insert(0, primary_symptom)

    symptom_assessments: list[SymptomAssessment] = []
    seen_symptom_routes: set[str] = set()
    for symptom in assessment.symptom_assessments[:4]:
        route = _trim(symptom.route, 40).lower()
        evidence = _trim(symptom.evidence, 160)
        if (
            route not in allowed_routes
            or route in seen_symptom_routes
            or not _has_grounded_evidence(text, evidence)
        ):
            continue
        seen_symptom_routes.add(route)
        symptom_assessments.append(
            SymptomAssessment(
                route=route,
                evidence=evidence,
                onset=_validated_evidence_value(
                    text,
                    symptom.onset,
                    {"sudden", "gradual", "unknown"},
                ),
                severity=_validated_evidence_value(
                    text,
                    symptom.severity,
                    {"mild", "moderate", "severe", "unknown"},
                ),
                is_new_or_changed=_validated_evidence_value(
                    text,
                    symptom.is_new_or_changed,
                    {"true", "false", "unknown"},
                ),
                findings=_validated_findings(text, symptom.findings),
                negated_findings=_validated_findings(
                    text,
                    symptom.negated_findings,
                    force_absent=True,
                ),
            )
        )

    return ChiefComplaintAssessment(
        primary_symptom=primary_symptom,
        primary_evidence=primary_evidence,
        symptom_domains=cast(
            list[str | RouteEvidence],
            list(dict.fromkeys(supported_domains))[:4],
        ),
        onset=onset,
        severity=severity,
        is_new_or_changed=is_new_or_changed,
        findings=findings,
        negated_findings=negated,
        route_candidates=cast(
            list[str | RouteEvidence],
            list(dict.fromkeys(route_candidates))[:4],
        ),
        symptom_assessments=symptom_assessments,
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
1. primary_symptom只能是單一字串：
   {route_values}。
   symptom_domains及route_candidates必須是物件陣列，每個物件只能包含
   route與evidence；route只能使用上述值，evidence必須逐字取自病人原文。
2. onset.value只能是sudden、gradual、unknown。
3. severity.value只能是mild、moderate、severe、unknown。
4. is_new_or_changed.value只能是true、false、unknown。
5. finding.code只能使用下列代碼：
   {finding_values}。
6. findings只放present；negated_findings只放病人明確否認的項目。
7. 每個非unknown值、route及finding都必須附原文逐字evidence。
8. 即使有多個症狀，symptom_domains及route_candidates仍不可輸出字串以外
   的route值，也不可使用domain、value等其他欄位名稱。
9. 有多個症狀時，symptom_assessments要為每個症狀分別整理嚴重程度、發作型態、
   是否新發或改變及相關finding；不可把一個症狀的資訊套用到另一個症狀。

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
  "symptom_domains": [
    {{"route": "unknown", "evidence": ""}}
  ],
  "onset": {{"value": "unknown", "evidence": ""}},
  "severity": {{"value": "unknown", "evidence": ""}},
  "is_new_or_changed": {{"value": "unknown", "evidence": ""}},
  "findings": [
    {{"code": "{example_finding}", "status": "present", "evidence": "原文片段"}}
  ],
  "negated_findings": [],
  "route_candidates": [
    {{"route": "unknown", "evidence": ""}}
  ],
  "symptom_assessments": [
    {{
      "route": "unknown",
      "evidence": "",
      "onset": {{"value": "unknown", "evidence": ""}},
      "severity": {{"value": "unknown", "evidence": ""}},
      "is_new_or_changed": {{"value": "unknown", "evidence": ""}},
      "findings": [],
      "negated_findings": []
    }}
  ],
  "uncertain_fields": []
}}
""".strip()


def prioritized_routes(
    assessment: ChiefComplaintAssessment | None,
    risk_profile: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Rank evidenced symptom routes while retaining every supported route."""
    if not assessment:
        return []
    allowed_routes = supported_routes()
    candidates = [
        route
        for route in assessment.route_candidates
        if isinstance(route, str) and route in allowed_routes
    ]
    profiles = {
        profile.route: profile
        for profile in assessment.symptom_assessments
        if profile.route in allowed_routes
    }
    for route in profiles:
        if route not in candidates:
            candidates.append(route)
    if (
        assessment.primary_symptom in allowed_routes
        and assessment.primary_evidence
        and assessment.primary_symptom not in candidates
    ):
        candidates.insert(0, assessment.primary_symptom)

    risks = risk_profile or {}
    rules = load_safety_rules()["structured_rules"]
    route_risks: dict[str, set[str]] = {route: set() for route in allowed_routes}
    for rule in rules:
        primary_routes = rule.get("when", {}).get("primary_in", [])
        requested_risks = {
            *rule.get("when", {}).get("all_risks", []),
            *rule.get("when", {}).get("any_risks", []),
        }
        for route in primary_routes:
            if route in route_risks:
                route_risks[route].update(requested_risks)

    severity_score = {"severe": 30, "moderate": 20, "mild": 10}
    onset_score = {"sudden": 12, "gradual": 4}

    def priority(route: str) -> int:
        profile = profiles.get(route)
        if not profile:
            return 0
        score = severity_score.get(profile.severity.value, 0)
        score += onset_score.get(profile.onset.value, 0)
        score += 6 if profile.is_new_or_changed.value == "true" else 0
        score += len({finding.code for finding in profile.findings if finding.status == "present"})
        score += 3 * sum(
            bool(risks.get(risk, {}).get("present")) for risk in route_risks.get(route, set())
        )
        return score

    return sorted(candidates, key=priority, reverse=True)


def preferred_route(
    assessment: ChiefComplaintAssessment | None,
    risk_profile: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    if not assessment:
        return None
    ranked = prioritized_routes(assessment, risk_profile)
    if assessment.symptom_assessments and ranked:
        return ranked[0]
    allowed_routes = supported_routes()
    if assessment.primary_symptom in {*allowed_routes, "other"} and assessment.primary_evidence:
        return assessment.primary_symptom
    supported = [
        route
        for route in assessment.route_candidates
        if isinstance(route, str) and route in allowed_routes
    ]
    return supported[0] if len(supported) == 1 else None
