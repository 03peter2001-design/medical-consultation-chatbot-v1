"""Deterministic profile-derived graph for explicitly selected research experiments.

This graph uses provisional route clues as likelihood assumptions. It does not
replace the manifest-verified PrimeKG graph or confer clinical approval.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from .graph import SCHEMA_VERSION, KnowledgeGraph, MedKGIAssetError
from .models import DiseaseNode, DiseaseSymptomEdge, GraphProvenance, SymptomNode

NEUTRAL_LIKELIHOOD = 0.5
SUPPORTING_LIKELIHOOD = 0.8
OPPOSING_LIKELIHOOD = 0.2


def profile_disease_id(route: str, profile_id: str) -> str:
    """Return the stable experimental node ID for a route profile."""
    return f"profile:{route}:{profile_id}"


def fact_symptom_id(code: str) -> str:
    """Return the stable experimental node ID for a clinical fact."""
    return f"fact:{code}"


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MedKGIAssetError(f"{field} must be non-empty text")
    return value.strip()


def _profile_likelihood(clue: dict[str, Any], location: str) -> float:
    status = clue.get("status")
    direction = clue.get("direction")
    weight = clue.get("weight")
    if status not in {"present", "absent"} or direction not in {"support", "oppose"}:
        raise MedKGIAssetError(f"{location} has invalid status or direction")
    if isinstance(weight, bool) or not isinstance(weight, int) or weight < 1:
        raise MedKGIAssetError(f"{location} has invalid weight")
    # A positive observation supports the disease for present/support and
    # absent/oppose; the other combinations lower its likelihood. The current
    # provisional profiles mostly use unit weights, so weight is validated but
    # deliberately not converted into an undocumented probability scale.
    positive_support = (status == "present") == (direction == "support")
    return SUPPORTING_LIKELIHOOD if positive_support else OPPOSING_LIKELIHOOD


def build_profile_experiment_graph(
    documents: Mapping[str, dict[str, Any]],
    *,
    primekg_provenance: GraphProvenance,
    allowed_fact_codes: Iterable[str] = (),
) -> KnowledgeGraph:
    """Build a research graph from validated route documents and verified PrimeKG provenance.

    ``documents`` must come from ``load_profile_document``. The caller is
    responsible for loading and hash-verifying PrimeKG before calling this.
    Likelihoods here are experimental assumptions derived from profile clue
    polarity, never PrimeKG disease-symptom probabilities.
    """
    if not documents:
        raise MedKGIAssetError("profile experiment requires route documents")
    if primekg_provenance.source_name != "PrimeKG" or not re.fullmatch(
        r"[0-9a-f]{64}", primekg_provenance.graph_sha256
    ):
        raise MedKGIAssetError("profile experiment requires verified PrimeKG provenance")

    catalog_facts = {_required_text(code, "allowed_fact_codes") for code in allowed_fact_codes}
    diseases: dict[str, DiseaseNode] = {}
    symptoms: dict[str, SymptomNode] = {}
    edges: list[DiseaseSymptomEdge] = []
    source_records: list[dict[str, str]] = []

    for route, document in sorted(documents.items()):
        route = _required_text(route, "route")
        if not isinstance(document, dict) or document.get("route") != route:
            raise MedKGIAssetError(f"{route} profile document has an invalid route")
        version = _required_text(document.get("profile_version"), f"{route}.profile_version")
        profiles = document.get("profiles")
        if not isinstance(profiles, list) or not profiles:
            raise MedKGIAssetError(f"{route} has no disease profiles")

        profile_likelihoods: dict[str, dict[str, float]] = {}
        route_facts: set[str] = set(catalog_facts)
        for index, profile in enumerate(profiles):
            location = f"{route}.profiles[{index}]"
            if not isinstance(profile, dict):
                raise MedKGIAssetError(f"{location} must be an object")
            profile_id = _required_text(profile.get("id"), f"{location}.id")
            disease_id = profile_disease_id(route, profile_id)
            if disease_id in diseases:
                raise MedKGIAssetError(f"duplicate profile disease: {disease_id}")
            diseases[disease_id] = DiseaseNode(
                disease_id,
                _required_text(profile.get("name"), f"{location}.name"),
            )
            clues = profile.get("clues")
            if not isinstance(clues, list) or not clues:
                raise MedKGIAssetError(f"{location} has no clinical facts")
            likelihoods: dict[str, float] = {}
            for clue_index, clue in enumerate(clues):
                clue_location = f"{location}.clues[{clue_index}]"
                if not isinstance(clue, dict):
                    raise MedKGIAssetError(f"{clue_location} must be an object")
                fact = _required_text(clue.get("fact"), f"{clue_location}.fact")
                likelihood = _profile_likelihood(clue, clue_location)
                previous = likelihoods.get(fact)
                if previous is not None and previous != likelihood:
                    raise MedKGIAssetError(
                        f"contradictory clue polarity for {disease_id} and {fact}"
                    )
                likelihoods[fact] = likelihood
                route_facts.add(fact)
            profile_likelihoods[disease_id] = likelihoods

        if not route_facts:
            raise MedKGIAssetError(f"{route} has no clinical facts")
        for fact in sorted(route_facts):
            symptom_id = fact_symptom_id(fact)
            symptoms.setdefault(symptom_id, SymptomNode(symptom_id, fact.replace("_", " ")))
        for disease_id, likelihoods in sorted(profile_likelihoods.items()):
            for fact in sorted(route_facts):
                edges.append(
                    DiseaseSymptomEdge(
                        disease_id,
                        fact_symptom_id(fact),
                        likelihoods.get(fact, NEUTRAL_LIKELIHOOD),
                    )
                )

        document_hash = hashlib.sha256(
            json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        source_records.append({"route": route, "version": version, "sha256": document_hash})

    payload = {
        "primekg_sha256": primekg_provenance.graph_sha256,
        "allowed_fact_codes": sorted(catalog_facts),
        "profiles": source_records,
        "diseases": sorted(diseases),
        "symptoms": sorted(symptoms),
        "edges": [(edge.disease_id, edge.symptom_id, edge.probability) for edge in edges],
    }
    derived_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    provenance = GraphProvenance(
        schema_version=SCHEMA_VERSION,
        knowledge_graph_version=f"profile-experiment-{derived_hash[:12]}",
        created_at="deterministic-profile-derivation",
        source_name="PrimeKG-verified/profile-derived experiment",
        source_uri=json.dumps(
            {
                "primekg_sha256": primekg_provenance.graph_sha256,
                "allowed_fact_codes_sha256": hashlib.sha256(
                    json.dumps(sorted(catalog_facts), separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
                "profiles": source_records,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        source_license=primekg_provenance.source_license,
        review_status="research_unreviewed",
        reviewer="none",
        review_date="not-reviewed",
        graph_sha256=derived_hash,
    )
    return KnowledgeGraph(provenance, diseases, symptoms, tuple(edges))
