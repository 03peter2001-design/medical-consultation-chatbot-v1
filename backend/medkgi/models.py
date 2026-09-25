"""Immutable state and result models for local MedKGI inference.

Outputs are provisional decision support only. They are not formal diagnoses
and must be reviewed by a qualified clinician before clinical action.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

EntityKind = Literal["disease", "symptom"]
EvidenceStatus = Literal["positive", "negative"]
DecisionAction = Literal["inquire", "final", "handoff"]


@dataclass(frozen=True)
class GraphProvenance:
    schema_version: int
    knowledge_graph_version: str
    created_at: str
    source_name: str
    source_uri: str
    source_license: str
    review_status: str
    reviewer: str
    review_date: str
    graph_sha256: str
    embedding_sha256: str = ""
    embedding_model: str = ""


@dataclass(frozen=True)
class DiseaseNode:
    entity_id: str
    name: str
    aliases: tuple[str, ...] = ()
    prior: float | None = None


@dataclass(frozen=True)
class SymptomNode:
    entity_id: str
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiseaseSymptomEdge:
    disease_id: str
    symptom_id: str
    probability: float | None = None


@dataclass(frozen=True)
class Alignment:
    query: str
    kind: EntityKind
    entity_id: str
    entity_name: str
    method: Literal["exact", "edit_distance", "embedding"]
    score: float


@dataclass(frozen=True)
class EvidenceObservation:
    symptom_id: str
    status: EvidenceStatus
    source_text: str = ""
    turn: int = 0

    def __post_init__(self) -> None:
        if not self.symptom_id.strip():
            raise ValueError("symptom_id must not be empty")
        if self.turn < 0:
            raise ValueError("evidence turn must be non-negative")


@dataclass(frozen=True)
class OSCEState:
    """Structured, evidence-only diagnostic state inspired by OSCE records."""

    demographics: tuple[tuple[str, str], ...] = ()
    chief_complaint: str = ""
    medical_history: tuple[str, ...] = ()
    examinations: tuple[str, ...] = ()
    evidence: tuple[EvidenceObservation, ...] = ()
    asked_symptom_ids: tuple[str, ...] = ()
    candidate_history: tuple[tuple[str, ...], ...] = ()
    turn_count: int = 0

    def __post_init__(self) -> None:
        if self.turn_count < 0:
            raise ValueError("turn_count must be non-negative")
        symptom_ids = [item.symptom_id for item in self.evidence]
        if len(symptom_ids) != len(set(symptom_ids)):
            raise ValueError("OSCE evidence must contain one current fact per symptom")

    @property
    def positive_symptom_ids(self) -> tuple[str, ...]:
        return tuple(item.symptom_id for item in self.evidence if item.status == "positive")

    @property
    def negative_symptom_ids(self) -> tuple[str, ...]:
        return tuple(item.symptom_id for item in self.evidence if item.status == "negative")

    def with_observation(
        self,
        symptom_id: str,
        status: EvidenceStatus,
        *,
        source_text: str = "",
    ) -> OSCEState:
        """Add or explicitly revise one confirmed symptom observation."""

        observation = EvidenceObservation(
            symptom_id=symptom_id.strip(),
            status=status,
            source_text=source_text.strip(),
            turn=self.turn_count,
        )
        retained = tuple(item for item in self.evidence if item.symptom_id != symptom_id)
        asked = tuple(dict.fromkeys((*self.asked_symptom_ids, symptom_id)))
        return replace(self, evidence=(*retained, observation), asked_symptom_ids=asked)

    def with_inquiry(self, symptom_id: str) -> OSCEState:
        """Record that a question was asked and consume one dialogue turn."""

        normalized = symptom_id.strip()
        if not normalized:
            raise ValueError("inquiry symptom_id must not be empty")
        asked = tuple(dict.fromkeys((*self.asked_symptom_ids, normalized)))
        return replace(self, asked_symptom_ids=asked, turn_count=self.turn_count + 1)

    def with_candidate_snapshot(self, disease_ids: tuple[str, ...]) -> OSCEState:
        snapshot = tuple(sorted(set(disease_ids)))
        return replace(self, candidate_history=(*self.candidate_history, snapshot))


@dataclass(frozen=True)
class DiseasePosterior:
    disease_id: str
    disease_name: str
    probability: float
    supporting_symptom_ids: tuple[str, ...]
    contradicting_symptom_ids: tuple[str, ...]


@dataclass(frozen=True)
class InquiryCandidate:
    symptom_id: str
    symptom_name: str
    information_gain: float
    marginal_probability: float
    refutation_margin: float


@dataclass(frozen=True)
class DiagnosticDecision:
    action: DecisionAction
    reason: str
    next_symptom_id: str | None = None
    next_symptom_name: str | None = None


@dataclass(frozen=True)
class MedKGIResult:
    """A provisional KG-grounded result, never a clinician-confirmed diagnosis."""

    candidates: tuple[DiseasePosterior, ...]
    inquiries: tuple[InquiryCandidate, ...]
    decision: DiagnosticDecision
    state: OSCEState
    provenance: GraphProvenance
    alignments: tuple[Alignment, ...] = ()
    unmatched_terms: tuple[str, ...] = ()
