"""Transport-independent orchestration of the local MedKGI method.

This research implementation generates provisional, knowledge-graph-grounded
decision support. It is not a medical device or a formal diagnosis and may not
be used for patient care without qualified clinical validation and review.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .graph import EntityAligner, KnowledgeGraph
from .inference import disease_posteriors, information_gain_candidates
from .models import Alignment, DiagnosticDecision, MedKGIResult, OSCEState


@dataclass(frozen=True)
class MedKGIConfig:
    candidate_cap: int = 5
    turn_limit: int = 20
    stagnation_turns: int = 2
    smoothing: float = 1e-6
    minimum_information_gain: float = 1e-12

    def __post_init__(self) -> None:
        if not 1 <= self.candidate_cap <= 5:
            raise ValueError("candidate_cap must be between one and the MedKGI maximum of five")
        if self.turn_limit < 1:
            raise ValueError("turn_limit must be positive")
        if self.stagnation_turns < 1:
            raise ValueError("stagnation_turns must be positive")
        if not 0 < self.smoothing < 0.5:
            raise ValueError("smoothing must be in (0, 0.5)")
        if self.minimum_information_gain < 0:
            raise ValueError("minimum_information_gain must be non-negative")


class MedKGICore:
    """Pure MedKGI state transition engine with no model, transport, or network I/O."""

    def __init__(
        self,
        graph: KnowledgeGraph,
        *,
        aligner: EntityAligner | None = None,
        config: MedKGIConfig | None = None,
    ):
        self.graph = graph
        self.aligner = aligner or EntityAligner(graph)
        self.config = config or MedKGIConfig()

    def assess(
        self,
        state: OSCEState,
        *,
        candidate_terms: Sequence[str] = (),
        candidate_ids: Sequence[str] = (),
        approved_query_symptom_ids: Sequence[str] | None = None,
        prior_weights: Mapping[str, float] | None = None,
    ) -> MedKGIResult:
        """Compute one deterministic diagnostic update and optional next inquiry."""

        aligned: list[Alignment] = []
        unmatched: list[str] = []
        proposed_ids: list[str] = []
        for term in candidate_terms:
            match = self.aligner.align(term, "disease")
            if match is None or not self.graph.symptom_edges(match.entity_id):
                unmatched.append(term)
                continue
            aligned.append(match)
            proposed_ids.append(match.entity_id)
        for disease_id in candidate_ids:
            if disease_id not in self.graph.diseases or not self.graph.symptom_edges(disease_id):
                unmatched.append(disease_id)
            else:
                proposed_ids.append(disease_id)
        if not proposed_ids:
            proposed_ids.extend(self._candidates_from_positive_evidence(state))
        unique_ids = tuple(dict.fromkeys(proposed_ids))

        if not unique_ids:
            decision = DiagnosticDecision(
                action="handoff",
                reason="no_kg_grounded_candidates",
            )
            return MedKGIResult(
                candidates=(),
                inquiries=(),
                decision=decision,
                state=state,
                provenance=self.graph.provenance,
                alignments=tuple(aligned),
                unmatched_terms=tuple(unmatched),
            )

        preliminary = disease_posteriors(
            self.graph,
            unique_ids,
            state,
            smoothing=self.config.smoothing,
            prior_weights=prior_weights,
        )
        selected_ids = tuple(item.disease_id for item in preliminary[: self.config.candidate_cap])
        candidates = disease_posteriors(
            self.graph,
            selected_ids,
            state,
            smoothing=self.config.smoothing,
            prior_weights=prior_weights,
        )
        current_ids = tuple(item.disease_id for item in candidates)
        inquiries = information_gain_candidates(
            self.graph,
            candidates,
            state,
            smoothing=self.config.smoothing,
        )
        if approved_query_symptom_ids is not None:
            approved = set(approved_query_symptom_ids)
            unknown = sorted(approved.difference(self.graph.symptoms))
            if unknown:
                raise ValueError(f"approved query symptoms are not in the graph: {unknown}")
            inquiries = tuple(item for item in inquiries if item.symptom_id in approved)
        stagnant = self._is_stagnant(state, current_ids)
        state_with_snapshot = state.with_candidate_snapshot(current_ids)

        if state.turn_count >= self.config.turn_limit:
            decision = DiagnosticDecision(action="final", reason="turn_limit")
            updated_state = state_with_snapshot
        elif stagnant:
            refuting = next(
                (
                    inquiry
                    for inquiry in inquiries
                    if inquiry.refutation_margin > 0
                    and inquiry.information_gain >= self.config.minimum_information_gain
                ),
                None,
            )
            if refuting is None:
                decision = DiagnosticDecision(
                    action="final",
                    reason="stagnation_no_refuting_symptom",
                )
                updated_state = state_with_snapshot
            else:
                decision = DiagnosticDecision(
                    action="inquire",
                    reason="stagnation_refutation",
                    next_symptom_id=refuting.symptom_id,
                    next_symptom_name=refuting.symptom_name,
                )
                updated_state = state_with_snapshot
        elif not inquiries:
            decision = DiagnosticDecision(action="final", reason="no_unobserved_symptoms")
            updated_state = state_with_snapshot
        elif inquiries[0].information_gain < self.config.minimum_information_gain:
            decision = DiagnosticDecision(action="final", reason="no_information_gain")
            updated_state = state_with_snapshot
        else:
            selected = inquiries[0]
            decision = DiagnosticDecision(
                action="inquire",
                reason="maximum_information_gain",
                next_symptom_id=selected.symptom_id,
                next_symptom_name=selected.symptom_name,
            )
            updated_state = state_with_snapshot

        return MedKGIResult(
            candidates=candidates,
            inquiries=inquiries,
            decision=decision,
            state=updated_state,
            provenance=self.graph.provenance,
            alignments=tuple(aligned),
            unmatched_terms=tuple(unmatched),
        )

    def _candidates_from_positive_evidence(self, state: OSCEState) -> tuple[str, ...]:
        scores: dict[str, float] = {}
        for symptom_id in state.positive_symptom_ids:
            if symptom_id not in self.graph.symptoms:
                continue
            for disease_id in self.graph.disease_ids_for_symptom(symptom_id):
                scores[disease_id] = scores.get(disease_id, 0.0) + self.graph.edge_probability(
                    disease_id,
                    symptom_id,
                    self.config.smoothing,
                )
        ranked = sorted(
            scores,
            key=lambda disease_id: (
                -scores[disease_id],
                self.graph.diseases[disease_id].name.casefold(),
                disease_id,
            ),
        )
        return tuple(ranked[: self.config.candidate_cap])

    def _is_stagnant(self, state: OSCEState, current_ids: tuple[str, ...]) -> bool:
        snapshot = tuple(sorted(current_ids))
        unchanged = 0
        for previous in reversed(state.candidate_history):
            if previous != snapshot:
                break
            unchanged += 1
        return unchanged >= self.config.stagnation_turns
