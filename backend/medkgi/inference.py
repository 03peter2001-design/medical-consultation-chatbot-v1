"""Bayesian belief updates and information-gain selection for MedKGI.

All probabilities are research decision-support signals, not disease risk or a
formal diagnosis. A qualified clinician must review all outputs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from .graph import KnowledgeGraph
from .models import DiseasePosterior, InquiryCandidate, OSCEState


def _normalize(weights: Mapping[str, float], smoothing: float) -> dict[str, float]:
    """Apply explicit additive smoothing and normalize a finite distribution."""

    if not weights:
        raise ValueError("cannot normalize an empty distribution")
    if not 0 < smoothing < 0.5:
        raise ValueError("smoothing must be in (0, 0.5)")
    adjusted: dict[str, float] = {}
    for key, value in weights.items():
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0:
            raise ValueError("probability weights must be finite and non-negative")
        adjusted[key] = numeric + smoothing
    total = sum(adjusted.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("probability weights cannot be normalized")
    return {key: value / total for key, value in adjusted.items()}


def shannon_entropy(probabilities: Sequence[float]) -> float:
    """Return Shannon entropy in nats, ignoring exact zero values."""

    values = [float(value) for value in probabilities]
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("entropy probabilities must be finite and non-negative")
    total = sum(values)
    if not math.isclose(total, 1.0, rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError("entropy probabilities must sum to one")
    return -sum(value * math.log(value) for value in values if value > 0)


def disease_posteriors(
    graph: KnowledgeGraph,
    disease_ids: Sequence[str],
    state: OSCEState,
    *,
    smoothing: float,
    prior_weights: Mapping[str, float] | None = None,
) -> tuple[DiseasePosterior, ...]:
    """Update candidate disease beliefs with conditionally independent evidence."""

    unique_ids = tuple(dict.fromkeys(disease_ids))
    if not unique_ids:
        return ()
    if any(disease_id not in graph.diseases for disease_id in unique_ids):
        raise ValueError("posterior candidate is not present in the knowledge graph")
    if prior_weights is None:
        raw_priors = {
            disease_id: graph.diseases[disease_id].prior
            if graph.diseases[disease_id].prior is not None
            else 1.0
            for disease_id in unique_ids
        }
    else:
        raw_priors = {
            disease_id: float(prior_weights.get(disease_id, 0.0)) for disease_id in unique_ids
        }
    priors = _normalize(raw_priors, smoothing)

    log_weights: dict[str, float] = {}
    positive = set(state.positive_symptom_ids)
    negative = set(state.negative_symptom_ids)
    for disease_id in unique_ids:
        log_weight = math.log(priors[disease_id])
        for symptom_id in positive:
            log_weight += math.log(graph.edge_probability(disease_id, symptom_id, smoothing))
        for symptom_id in negative:
            probability = graph.edge_probability(disease_id, symptom_id, smoothing)
            log_weight += math.log(max(smoothing, 1 - probability))
        log_weights[disease_id] = log_weight

    maximum = max(log_weights.values())
    posterior = _normalize(
        {disease_id: math.exp(value - maximum) for disease_id, value in log_weights.items()},
        smoothing,
    )
    ranked = []
    for disease_id, probability in posterior.items():
        connected = {edge.symptom_id for edge in graph.symptom_edges(disease_id)}
        ranked.append(
            DiseasePosterior(
                disease_id=disease_id,
                disease_name=graph.diseases[disease_id].name,
                probability=probability,
                supporting_symptom_ids=tuple(sorted(positive & connected)),
                contradicting_symptom_ids=tuple(sorted(negative & connected)),
            )
        )
    return tuple(
        sorted(
            ranked,
            key=lambda item: (-item.probability, item.disease_name.casefold(), item.disease_id),
        )
    )


def information_gain_candidates(
    graph: KnowledgeGraph,
    posteriors: Sequence[DiseasePosterior],
    state: OSCEState,
    *,
    smoothing: float,
) -> tuple[InquiryCandidate, ...]:
    """Rank unobserved, unasked symptoms by expected entropy reduction."""

    if not posteriors:
        return ()
    prior = {item.disease_id: item.probability for item in posteriors}
    prior_entropy = shannon_entropy(tuple(prior.values()))
    excluded = {
        *state.positive_symptom_ids,
        *state.negative_symptom_ids,
        *state.asked_symptom_ids,
    }
    symptom_ids = sorted(
        {
            edge.symptom_id
            for disease_id in prior
            for edge in graph.symptom_edges(disease_id)
            if edge.symptom_id not in excluded
        },
        key=lambda symptom_id: (graph.symptoms[symptom_id].name.casefold(), symptom_id),
    )
    top_disease_id = posteriors[0].disease_id
    inquiries = []
    for symptom_id in symptom_ids:
        likelihoods = {
            disease_id: graph.edge_probability(disease_id, symptom_id, smoothing)
            for disease_id in prior
        }
        marginal = sum(
            prior[disease_id] * likelihood for disease_id, likelihood in likelihoods.items()
        )
        marginal = min(1 - smoothing, max(smoothing, marginal))
        positive_posterior = _normalize(
            {disease_id: prior[disease_id] * likelihoods[disease_id] for disease_id in prior},
            smoothing,
        )
        negative_posterior = _normalize(
            {disease_id: prior[disease_id] * (1 - likelihoods[disease_id]) for disease_id in prior},
            smoothing,
        )
        expected_entropy = marginal * shannon_entropy(tuple(positive_posterior.values())) + (
            1 - marginal
        ) * shannon_entropy(tuple(negative_posterior.values()))
        competitor_mass = 1 - prior[top_disease_id]
        competitor_probability = (
            sum(
                prior[disease_id] * likelihoods[disease_id]
                for disease_id in prior
                if disease_id != top_disease_id
            )
            / competitor_mass
            if competitor_mass > smoothing
            else 0.0
        )
        inquiries.append(
            InquiryCandidate(
                symptom_id=symptom_id,
                symptom_name=graph.symptoms[symptom_id].name,
                information_gain=max(0.0, prior_entropy - expected_entropy),
                marginal_probability=marginal,
                refutation_margin=likelihoods[top_disease_id] - competitor_probability,
            )
        )
    return tuple(
        sorted(
            inquiries,
            key=lambda item: (
                -item.information_gain,
                item.symptom_name.casefold(),
                item.symptom_id,
            ),
        )
    )
