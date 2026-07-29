"""Structured model contracts used by the AMIE-inspired graph."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

ChiefRoute = str
FindingStatus = Literal["present", "absent", "unknown"]


class EvidenceValue(BaseModel):
    value: str = "unknown"
    evidence: str = ""


class ChiefFinding(BaseModel):
    # The deployed JSON rule set owns the vocabulary and validates this value.
    code: str
    status: FindingStatus = "unknown"
    evidence: str = ""


class RouteEvidence(BaseModel):
    """A symptom route paired with verbatim evidence from the complaint."""

    route: ChiefRoute
    evidence: str = ""


class SymptomEvidence(BaseModel):
    """A whitelist symptom concept paired with verbatim patient evidence."""

    code: str
    evidence: str = ""


class SymptomAssessment(BaseModel):
    """Evidence-grounded facts scoped to one symptom route."""

    route: ChiefRoute
    evidence: str = ""
    symptom_code: str = "unknown"
    onset_time: EvidenceValue = Field(default_factory=EvidenceValue)
    onset: EvidenceValue = Field(default_factory=EvidenceValue)
    course: EvidenceValue = Field(default_factory=EvidenceValue)
    duration: EvidenceValue = Field(default_factory=EvidenceValue)
    severity: EvidenceValue = Field(default_factory=EvidenceValue)
    is_new_or_changed: EvidenceValue = Field(default_factory=EvidenceValue)
    findings: list[ChiefFinding] = Field(default_factory=list)
    negated_findings: list[ChiefFinding] = Field(default_factory=list)


class ChiefComplaintAssessment(BaseModel):
    """Evidence-grounded semantic extraction, not a diagnosis or triage."""

    primary_symptom: ChiefRoute = "unknown"
    primary_evidence: str = ""
    primary_symptom_code: str = "unknown"
    symptoms: list[SymptomEvidence] = Field(default_factory=list)
    symptom_domains: list[ChiefRoute | RouteEvidence] = Field(default_factory=list)
    onset_time: EvidenceValue = Field(default_factory=EvidenceValue)
    onset: EvidenceValue = Field(default_factory=EvidenceValue)
    course: EvidenceValue = Field(default_factory=EvidenceValue)
    duration: EvidenceValue = Field(default_factory=EvidenceValue)
    severity: EvidenceValue = Field(default_factory=EvidenceValue)
    is_new_or_changed: EvidenceValue = Field(default_factory=EvidenceValue)
    findings: list[ChiefFinding] = Field(default_factory=list)
    negated_findings: list[ChiefFinding] = Field(default_factory=list)
    route_candidates: list[ChiefRoute | RouteEvidence] = Field(default_factory=list)
    symptom_assessments: list[SymptomAssessment] = Field(default_factory=list)
    uncertain_fields: list[str] = Field(default_factory=list)

    @classmethod
    def from_model_text(cls, text: str) -> "ChiefComplaintAssessment":
        cleaned = text.strip()
        cleaned = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise
            payload = json.loads(cleaned[start : end + 1])
        if not isinstance(payload, dict):
            raise ValueError("語意抽取輸出必須是 JSON 物件")
        allowed_root = {
            "primary_symptom",
            "primary_evidence",
            "primary_symptom_code",
            "symptoms",
            "symptom_domains",
            "onset_time",
            "onset",
            "course",
            "duration",
            "severity",
            "is_new_or_changed",
            "findings",
            "negated_findings",
            "route_candidates",
            "symptom_assessments",
            "uncertain_fields",
        }
        unexpected = set(payload) - allowed_root
        if unexpected:
            raise ValueError(f"語意抽取含未允許欄位：{sorted(unexpected)}")
        for field in ("symptom_domains", "route_candidates"):
            for item in payload.get(field, []):
                if not isinstance(item, dict) or set(item) - {"route", "evidence"}:
                    raise ValueError(f"{field} 含未允許欄位")
        for item in payload.get("symptoms", []):
            if not isinstance(item, dict) or set(item) - {"code", "evidence"}:
                raise ValueError("symptoms 含未允許欄位")
        for field in (
            "onset_time",
            "onset",
            "course",
            "duration",
            "severity",
            "is_new_or_changed",
        ):
            item = payload.get(field, {})
            if not isinstance(item, dict) or set(item) - {"value", "evidence"}:
                raise ValueError(f"{field} 含未允許欄位")
        for field in ("findings", "negated_findings"):
            for item in payload.get(field, []):
                if not isinstance(item, dict) or set(item) - {
                    "code",
                    "status",
                    "evidence",
                }:
                    raise ValueError(f"{field} 含未允許欄位")
        symptom_allowed = {
            "route",
            "evidence",
            "symptom_code",
            "onset_time",
            "onset",
            "course",
            "duration",
            "severity",
            "is_new_or_changed",
            "findings",
            "negated_findings",
        }
        for item in payload.get("symptom_assessments", []):
            if not isinstance(item, dict) or set(item) - symptom_allowed:
                raise ValueError("symptom_assessments 含未允許欄位")
            for field in (
                "onset_time",
                "onset",
                "course",
                "duration",
                "severity",
                "is_new_or_changed",
            ):
                value = item.get(field, {})
                if not isinstance(value, dict) or set(value) - {
                    "value",
                    "evidence",
                }:
                    raise ValueError(f"symptom_assessments.{field} 含未允許欄位")
            for field in ("findings", "negated_findings"):
                values = item.get(field, [])
                if not isinstance(values, list):
                    raise ValueError(f"symptom_assessments.{field} 必須是陣列")
                if any(
                    not isinstance(value, dict) or set(value) - {"code", "status", "evidence"}
                    for value in values
                ):
                    raise ValueError(f"symptom_assessments.{field} 含未允許欄位")
        if hasattr(cls, "model_validate"):
            return cls.model_validate(payload)
        return cls.parse_obj(payload)

    def as_dict(self) -> dict[str, Any]:
        if hasattr(self, "model_dump"):
            return self.model_dump()
        return self.dict()


class AMIEEngineResult(BaseModel):
    action: Literal["ask", "complete", "handoff"]
    triage_level: Literal["urgent", "routine"] = "routine"
    data: dict[str, Any]
    decision: dict[str, Any] = Field(default_factory=dict)
    next_question: dict[str, Any] | None = None
    acknowledgement: str = ""
    handoff_reason: str = ""
    red_flags: list[dict[str, Any]] = Field(default_factory=list)
    differential_hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    disease_assessment: dict[str, Any] = Field(default_factory=dict)
    clinical_facts: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_gaps: list[str] = Field(default_factory=list)
    evidence_timeline: list[dict[str, Any]] = Field(default_factory=list)
    rag_sources: list[dict[str, Any]] = Field(default_factory=list)
    model_error: str = ""
