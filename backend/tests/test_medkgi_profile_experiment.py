"""Research-only graph construction tests with synthetic and public route metadata."""

import json
import unittest

from amie.disease_profiles import load_profile_document
from medkgi.graph import MedKGIAssetError
from medkgi.models import GraphProvenance
from medkgi.profile_experiment import (
    NEUTRAL_LIKELIHOOD,
    OPPOSING_LIKELIHOOD,
    SUPPORTING_LIKELIHOOD,
    build_profile_experiment_graph,
    fact_symptom_id,
    profile_disease_id,
)


def _primekg_provenance() -> GraphProvenance:
    return GraphProvenance(
        schema_version=1,
        knowledge_graph_version="synthetic-primekg",
        created_at="synthetic",
        source_name="PrimeKG",
        source_uri="synthetic-local-asset",
        source_license="test-only",
        review_status="research_unreviewed",
        reviewer="none",
        review_date="not-reviewed",
        graph_sha256="a" * 64,
    )


def _document() -> dict:
    return {
        "route": "chest",
        "profile_version": "synthetic-v1",
        "profiles": [
            {
                "id": "one",
                "name": "Synthetic disease one",
                "clues": [
                    {
                        "fact": "pressure",
                        "status": "present",
                        "direction": "support",
                        "weight": 1,
                    },
                    {
                        "fact": "sweating",
                        "status": "present",
                        "direction": "oppose",
                        "weight": 1,
                    },
                ],
            },
            {
                "id": "two",
                "name": "Synthetic disease two",
                "clues": [
                    {
                        "fact": "pressure",
                        "status": "absent",
                        "direction": "support",
                        "weight": 1,
                    }
                ],
            },
        ],
    }


class ProfileExperimentGraphTests(unittest.TestCase):
    def test_builds_dense_likelihood_graph_with_neutral_nonclue_edges(self):
        graph = build_profile_experiment_graph(
            {"chest": _document()}, primekg_provenance=_primekg_provenance()
        )

        one = profile_disease_id("chest", "one")
        two = profile_disease_id("chest", "two")
        pressure = fact_symptom_id("pressure")
        sweating = fact_symptom_id("sweating")
        self.assertEqual(len(graph.diseases), 2)
        self.assertEqual(len(graph.symptoms), 2)
        self.assertEqual(len(graph.edges), 4)
        self.assertEqual(graph.edge_probability(one, pressure, 1e-6), SUPPORTING_LIKELIHOOD)
        self.assertEqual(graph.edge_probability(one, sweating, 1e-6), OPPOSING_LIKELIHOOD)
        self.assertEqual(graph.edge_probability(two, pressure, 1e-6), OPPOSING_LIKELIHOOD)
        self.assertEqual(graph.edge_probability(two, sweating, 1e-6), NEUTRAL_LIKELIHOOD)

    def test_all_deployed_route_documents_build_without_patient_data(self):
        routes = ("chest", "headache", "abdomen")
        documents = {route: load_profile_document(route) for route in routes}
        graph = build_profile_experiment_graph(documents, primekg_provenance=_primekg_provenance())

        expected_diseases = sum(len(document["profiles"]) for document in documents.values())
        self.assertEqual(len(graph.diseases), expected_diseases)
        for route, document in documents.items():
            for profile in document["profiles"]:
                disease_id = profile_disease_id(route, profile["id"])
                self.assertTrue(graph.symptom_edges(disease_id))
                for clue in profile["clues"]:
                    self.assertIn(fact_symptom_id(clue["fact"]), graph.symptoms)
        self.assertEqual(graph.provenance.review_status, "research_unreviewed")
        self.assertIn("profile-derived", graph.provenance.source_name)
        source = json.loads(graph.provenance.source_uri)
        self.assertEqual(source["primekg_sha256"], "a" * 64)
        self.assertEqual(
            {item["route"]: item["version"] for item in source["profiles"]},
            {route: document["profile_version"] for route, document in documents.items()},
        )
        self.assertTrue(all(len(item["sha256"]) == 64 for item in source["profiles"]))

    def test_allowlisted_nonclue_fact_is_neutral_for_every_profile(self):
        graph = build_profile_experiment_graph(
            {"chest": _document()},
            primekg_provenance=_primekg_provenance(),
            allowed_fact_codes=("pressure", "unrelated_valid_fact"),
        )
        extra = fact_symptom_id("unrelated_valid_fact")
        self.assertIn(extra, graph.symptoms)
        for profile_id in ("one", "two"):
            self.assertEqual(
                graph.edge_probability(profile_disease_id("chest", profile_id), extra, 1e-6),
                NEUTRAL_LIKELIHOOD,
            )
        source = json.loads(graph.provenance.source_uri)
        self.assertEqual(len(source["allowed_fact_codes_sha256"]), 64)

    def test_repeated_build_has_stable_derived_hash(self):
        document = _document()
        first = build_profile_experiment_graph(
            {"chest": document}, primekg_provenance=_primekg_provenance()
        )
        second = build_profile_experiment_graph(
            {"chest": document}, primekg_provenance=_primekg_provenance()
        )
        self.assertEqual(first.provenance.graph_sha256, second.provenance.graph_sha256)

    def test_contradictory_clue_polarity_fails_closed(self):
        document = _document()
        document["profiles"][0]["clues"].append(
            {"fact": "pressure", "status": "present", "direction": "oppose", "weight": 1}
        )
        with self.assertRaisesRegex(MedKGIAssetError, "contradictory clue polarity"):
            build_profile_experiment_graph(
                {"chest": document}, primekg_provenance=_primekg_provenance()
            )

    def test_malformed_clues_and_missing_profiles_fail_closed(self):
        for replacement in (
            {"fact": "pressure", "status": "unknown", "direction": "support", "weight": 1},
            {"fact": "pressure", "status": "present", "direction": "support", "weight": 0},
        ):
            with self.subTest(replacement=replacement):
                document = _document()
                document["profiles"][0]["clues"][0] = replacement
                with self.assertRaises(MedKGIAssetError):
                    build_profile_experiment_graph(
                        {"chest": document}, primekg_provenance=_primekg_provenance()
                    )
        document = _document()
        document["profiles"] = []
        with self.assertRaisesRegex(MedKGIAssetError, "no disease profiles"):
            build_profile_experiment_graph(
                {"chest": document}, primekg_provenance=_primekg_provenance()
            )

    def test_requires_verified_primekg_provenance(self):
        provenance = _primekg_provenance()
        provenance = GraphProvenance(**{**vars(provenance), "graph_sha256": "tampered"})
        with self.assertRaisesRegex(MedKGIAssetError, "verified PrimeKG provenance"):
            build_profile_experiment_graph({"chest": _document()}, primekg_provenance=provenance)


if __name__ == "__main__":
    unittest.main()
