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


class ChiefComplaintAssessment(BaseModel):
    """Evidence-grounded semantic extraction, not a diagnosis or triage."""

    primary_symptom: ChiefRoute = "unknown"
    primary_evidence: str = ""
    symptom_domains: list[ChiefRoute | RouteEvidence] = Field(default_factory=list)
    onset: EvidenceValue = Field(default_factory=EvidenceValue)
    severity: EvidenceValue = Field(default_factory=EvidenceValue)
    is_new_or_changed: EvidenceValue = Field(default_factory=EvidenceValue)
    findings: list[ChiefFinding] = Field(default_factory=list)
    negated_findings: list[ChiefFinding] = Field(default_factory=list)
    route_candidates: list[ChiefRoute | RouteEvidence] = Field(default_factory=list)
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
        if isinstance(payload, dict):
            for field in ("symptom_domains", "route_candidates"):
                values = payload.get(field)
                if not isinstance(values, list):
                    continue
                payload[field] = [
                    {
                        "route": next(
                            (
                                item.get(key)
                                for key in ("route", "domain", "value", "code", "symptom")
                                if item.get(key)
                            ),
                            "",
                        ),
                        "evidence": item.get("evidence", ""),
                    }
                    if isinstance(item, dict)
                    else item
                    for item in values
                ]
        if hasattr(cls, "model_validate"):
            return cls.model_validate(payload)
        return cls.parse_obj(payload)

    def as_dict(self) -> dict[str, Any]:
        if hasattr(self, "model_dump"):
            return self.model_dump()
        return self.dict()


class DifferentialHypothesis(BaseModel):
    """A qualitative hypothesis, deliberately not a probability score."""

    condition: str
    supporting_evidence: list[str] = Field(default_factory=list)
    opposing_evidence: list[str] = Field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        if hasattr(self, "model_dump"):
            return self.model_dump()
        return self.dict()


class AMIEDecision(BaseModel):
    """One auditable state transition proposed by the reasoning agent."""

    action: Literal["ask", "complete"] = "ask"
    next_field: str | None = None
    extracted_facts: dict[str, str] = Field(default_factory=dict)
    negated_findings: list[str] = Field(default_factory=list)
    differential_hypotheses: list[DifferentialHypothesis] = Field(default_factory=list)
    knowledge_gaps: list[str] = Field(default_factory=list)
    needs_retrieval: bool = False
    retrieval_query: str = ""
    acknowledgement: str = ""
    audit_reason: str = ""

    @classmethod
    def from_model_text(cls, text: str) -> "AMIEDecision":
        """Parse a JSON object even if the provider wrapped it in a code fence."""
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
    red_flags: list[dict[str, str]] = Field(default_factory=list)
    differential_hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_gaps: list[str] = Field(default_factory=list)
    evidence_timeline: list[dict[str, Any]] = Field(default_factory=list)
    rag_sources: list[dict[str, Any]] = Field(default_factory=list)
    model_error: str = ""
