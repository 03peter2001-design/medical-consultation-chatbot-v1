import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from amie.medkgi_strategy import (
    METHOD,
    POSTERIOR_NOTE,
    PRIVATE_STATE_KEY,
    MedKGIDiagnosisStrategy,
    MedKGIStrategyError,
    _LocalPubMedBERTEmbedder,
)
from medkgi import KnowledgeGraph, MedKGIConfig, MedKGICore


def _graph():
    return KnowledgeGraph.from_records(
        version="synthetic-strategy-v1",
        diseases=[
            {"id": "acs", "name": "Acute coronary syndrome", "prior": 0.5},
            {
                "id": "gerd",
                "name": "Gastroesophageal reflux disease",
                "prior": 0.5,
            },
            {"id": "outside", "name": "Outside profile disease", "prior": 100.0},
        ],
        symptoms=[
            {"id": "pressure", "name": "chest pressure"},
            {"id": "sweat", "name": "diaphoresis"},
            {"id": "acid", "name": "acid regurgitation"},
            {"id": "palpitations", "name": "palpitations"},
        ],
        edges=[
            {"disease_id": "acs", "symptom_id": "pressure", "probability": 0.8},
            {"disease_id": "acs", "symptom_id": "sweat", "probability": 0.9},
            {"disease_id": "acs", "symptom_id": "acid", "probability": 0.1},
            {"disease_id": "gerd", "symptom_id": "pressure", "probability": 0.4},
            {"disease_id": "gerd", "symptom_id": "sweat", "probability": 0.1},
            {"disease_id": "gerd", "symptom_id": "acid", "probability": 0.9},
            {"disease_id": "outside", "symptom_id": "palpitations", "probability": 0.9},
        ],
    )


def _profiles():
    def profile(profile_id, name, display, must_not_miss, clues):
        return {
            "id": profile_id,
            "name": name,
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "100",
                    "display": display,
                    "verified": True,
                }
            ],
            "must_not_miss": must_not_miss,
            "review_status": "reviewed",
            "safety_rule_codes": ["synthetic-safety"] if must_not_miss else [],
            "clues": [{"fact": code} for code in clues],
        }

    return {
        "schema_version": 2,
        "profile_version": "chest-synthetic-v1",
        "route": "chest",
        "profiles": [
            profile(
                "acute_coronary_syndrome",
                "急性冠心症",
                "Acute coronary syndrome",
                True,
                ["chest_pressure", "diaphoresis"],
            ),
            profile(
                "gastroesophageal_reflux",
                "胃食道逆流",
                "Gastroesophageal reflux disease",
                False,
                ["chest_pressure", "acid_regurgitation"],
            ),
        ],
    }


def _fact(code, *, status="present", route="chest"):
    return {
        "code": code,
        "status": status,
        "evidence": f"synthetic {code}",
        "source": "synthetic_test",
        "turn": 1,
        "route": route,
    }


def _question(code):
    return {
        "field": f"synthetic_{code}",
        "semantic_options": {
            "yes": {"findings": [code]},
            "no": {"negated_findings": [code]},
        },
    }


class MedKGIDiagnosisStrategyTests(unittest.TestCase):
    def setUp(self):
        self.graph = _graph()
        self.strategy = MedKGIDiagnosisStrategy(MedKGICore(self.graph))
        self.profile_patch = patch(
            "amie.medkgi_strategy.load_profile_document",
            return_value=_profiles(),
        )
        self.profile_patch.start()

    def tearDown(self):
        self.profile_patch.stop()

    def test_scores_only_reviewed_profiles_and_marks_posterior_uncalibrated(self):
        result = self.strategy.score_diseases(
            [_fact("chest_pressure")],
            route="chest",
            previous_assessment=None,
        )

        self.assertEqual(result["method"], METHOD)
        self.assertEqual(result["posterior_interpretation"], POSTERIOR_NOTE)
        self.assertEqual(
            {item["id"] for item in result["ranked"]},
            {"acute_coronary_syndrome", "gastroesophageal_reflux"},
        )
        self.assertNotIn("outside", {item["id"] for item in result["ranked"]})
        self.assertAlmostEqual(
            sum(item["posterior_weight"] for item in result["ranked"]),
            1.0,
        )
        self.assertTrue(result["top"])
        acs = next(item for item in result["ranked"] if item["id"] == "acute_coronary_syndrome")
        self.assertEqual(acs["coding"][0]["display"], "Acute coronary syndrome")

    def test_cross_route_facts_are_excluded_by_allowlist(self):
        result = self.strategy.score_diseases(
            [_fact("chest_pressure", route="headache")],
            route="chest",
            previous_assessment=None,
        )

        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["top"], [])
        self.assertTrue(all(item["support_votes"] == 0 for item in result["ranked"]))

    def test_osce_history_and_asked_symptoms_persist_between_assessments(self):
        first = self.strategy.score_diseases(
            [_fact("chest_pressure")],
            route="chest",
            previous_assessment=None,
        )
        second = self.strategy.score_diseases(
            [_fact("chest_pressure"), _fact("diaphoresis")],
            route="chest",
            previous_assessment=first,
        )

        first_private = first[PRIVATE_STATE_KEY]
        second_private = second[PRIVATE_STATE_KEY]
        self.assertEqual(len(first_private["candidate_history"]), 1)
        self.assertEqual(len(second_private["candidate_history"]), 2)
        self.assertTrue(
            set(first_private["asked_symptom_ids"]) <= set(second_private["asked_symptom_ids"])
        )
        self.assertGreaterEqual(second_private["turn_count"], first_private["turn_count"])

    def test_only_the_question_amie_selected_is_recorded_as_asked(self):
        assessment = self.strategy.score_diseases(
            [_fact("chest_pressure")],
            route="chest",
            previous_assessment=None,
        )
        private = assessment[PRIVATE_STATE_KEY]
        proposed = private["decision"]["next_symptom_id"]
        self.assertNotIn(proposed, private["asked_symptom_ids"])
        selected_code = "acid_regurgitation" if proposed != "acid" else "diaphoresis"

        updated = self.strategy.record_selected_question(
            _question(selected_code),
            assessment,
            route="chest",
        )
        updated_private = updated[PRIVATE_STATE_KEY]
        selected_symptom = updated_private["fact_to_symptom"][selected_code]
        self.assertIn(selected_symptom, updated_private["asked_symptom_ids"])
        self.assertNotIn(proposed, updated_private["asked_symptom_ids"])
        self.assertEqual(updated_private["turn_count"], 1)

    def test_question_scores_use_only_core_information_gain_mapping(self):
        assessment = self.strategy.score_diseases(
            [_fact("chest_pressure")],
            route="chest",
            previous_assessment=None,
        )
        useful = [
            _question(code)
            for code in ("diaphoresis", "acid_regurgitation")
            if self.strategy.question_utility(_question(code), assessment, route="chest") > 0
        ]
        self.assertTrue(useful)
        question = useful[0]
        utility = self.strategy.question_utility(question, assessment, route="chest")
        frontier = self.strategy.build_candidate_frontier(assessment, max_candidates=5)
        score = self.strategy.funnel_question_score(question, frontier, route="chest")

        self.assertGreater(utility, 0)
        self.assertAlmostEqual(score["discrimination_score"], utility)
        self.assertTrue(score["target_fact_codes"])
        self.assertLessEqual(len(frontier["candidates"]), 5)

    def test_unaligned_profile_and_nonempty_unaligned_facts_fail_closed(self):
        bad_profiles = _profiles()
        bad_profiles["profiles"][0]["coding"][0]["display"] = "Unrelated disease name"
        bad_profiles["profiles"][0]["name"] = "無法對齊疾病"
        with patch(
            "amie.medkgi_strategy.load_profile_document",
            return_value=bad_profiles,
        ):
            with self.assertRaisesRegex(MedKGIStrategyError, "could not be aligned"):
                self.strategy.score_diseases(
                    [],
                    route="chest",
                    previous_assessment=None,
                )

        with self.assertRaisesRegex(MedKGIStrategyError, "could not be aligned"):
            self.strategy.score_diseases(
                [_fact("fever")],
                route="chest",
                previous_assessment=None,
            )

    def test_conflicting_profile_terms_fail_closed(self):
        bad_profiles = _profiles()
        bad_profiles["profiles"][0]["name"] = "Outside profile disease"
        with patch(
            "amie.medkgi_strategy.load_profile_document",
            return_value=bad_profiles,
        ):
            with self.assertRaisesRegex(MedKGIStrategyError, "conflicting"):
                self.strategy.score_diseases(
                    [],
                    route="chest",
                    previous_assessment=None,
                )

    def test_unaligned_profile_clue_fails_closed(self):
        bad_profiles = _profiles()
        bad_profiles["profiles"][0]["clues"].append({"fact": "unmapped_profile_clue"})
        with patch(
            "amie.medkgi_strategy.load_profile_document",
            return_value=bad_profiles,
        ):
            with self.assertRaisesRegex(MedKGIStrategyError, "allowlisted chest clinical facts"):
                self.strategy.score_diseases(
                    [],
                    route="chest",
                    previous_assessment=None,
                )

    def test_profile_aligned_to_disease_without_symptom_edges_fails_closed(self):
        graph = KnowledgeGraph.from_records(
            version="synthetic-orphan-v1",
            diseases=[
                {"id": "orphan", "name": "Acute coronary syndrome"},
                {"id": "grounded", "name": "Gastroesophageal reflux disease"},
            ],
            symptoms=[{"id": "acid", "name": "acid regurgitation"}],
            edges=[{"disease_id": "grounded", "symptom_id": "acid"}],
        )
        profiles = _profiles()
        profiles["profiles"] = profiles["profiles"][:1]
        with patch(
            "amie.medkgi_strategy.load_profile_document",
            return_value=profiles,
        ):
            with self.assertRaisesRegex(MedKGIStrategyError, "could not be aligned"):
                MedKGIDiagnosisStrategy(MedKGICore(graph)).score_diseases(
                    [], route="chest", previous_assessment=None
                )

    def test_core_final_decision_exposes_no_more_question_utility(self):
        strategy = MedKGIDiagnosisStrategy(
            MedKGICore(self.graph, config=MedKGIConfig(turn_limit=1))
        )
        first = strategy.score_diseases(
            [_fact("chest_pressure")], route="chest", previous_assessment=None
        )
        first = strategy.record_selected_question(_question("diaphoresis"), first, route="chest")
        final = strategy.score_diseases(
            [_fact("chest_pressure")], route="chest", previous_assessment=first
        )
        question = _question("diaphoresis")
        frontier = strategy.build_candidate_frontier(final, max_candidates=5)

        self.assertEqual(final[PRIVATE_STATE_KEY]["decision"]["action"], "final")
        self.assertEqual(strategy.question_utility(question, final, route="chest"), 0)
        self.assertEqual(
            strategy.funnel_question_score(question, frontier, route="chest")[
                "discrimination_score"
            ],
            0,
        )
        self.assertIn("diaphoresis", final["must_not_miss"][0]["missing_facts"])

    def test_startup_validation_rejects_an_unaligned_active_route(self):
        bad_profiles = _profiles()
        bad_profiles["profiles"][0]["coding"][0]["display"] = "Unrelated disease name"
        bad_profiles["profiles"][0]["name"] = "無法對齊疾病"
        with (
            patch("amie.medkgi_strategy.DISEASE_ROUTES", ("chest", "headache")),
            patch(
                "amie.medkgi_strategy.load_questionnaire_policy",
                return_value={"selection_strategy": "disease_vote"},
            ),
            patch(
                "amie.medkgi_strategy.load_profile_document",
                side_effect=lambda route: _profiles() if route == "chest" else bad_profiles,
            ),
        ):
            with self.assertRaisesRegex(MedKGIStrategyError, "could not be aligned"):
                self.strategy.validate_deployed_routes()

    def test_local_embedder_uses_cached_kg_vectors_and_embeds_only_query(self):
        with tempfile.TemporaryDirectory() as temporary:
            embedder = _LocalPubMedBERTEmbedder(
                Path(temporary),
                {"Canonical KG name": (0.0, 1.0)},
            )
            with patch.object(
                embedder,
                "_encode_uncached",
                return_value=[(1.0, 0.0)],
            ) as encode_uncached:
                vectors = embedder.encode(["new query", "Canonical KG name"])

        encode_uncached.assert_called_once_with(["new query"])
        self.assertEqual(vectors, [(1.0, 0.0), (0.0, 1.0)])

    def test_factory_accepts_duplicate_display_names_with_distinct_cached_vectors(self):
        base_graph = KnowledgeGraph.from_records(
            version="synthetic-duplicate-display-v1",
            diseases=[
                {"id": "d1", "name": "Duplicate display"},
                {"id": "d2", "name": "Duplicate display"},
            ],
            symptoms=[{"id": "s1", "name": "synthetic symptom"}],
            edges=[
                {"disease_id": "d1", "symptom_id": "s1"},
                {"disease_id": "d2", "symptom_id": "s1"},
            ],
        )
        graph = KnowledgeGraph(
            base_graph.provenance,
            base_graph.diseases,
            base_graph.symptoms,
            base_graph.edges,
            node_embeddings={
                "d1": (1.0, 0.0),
                "d2": (0.0, 1.0),
                "s1": (0.5, 0.5),
            },
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_directory = root / "model"
            model_directory.mkdir()
            with (
                patch("amie.medkgi_strategy.MedKGILoader.load", return_value=graph),
                patch("amie.medkgi_strategy.DISEASE_ROUTES", ()),
            ):
                strategy = MedKGIDiagnosisStrategy.from_environment(
                    {
                        "MEDKGI_MANIFEST_PATH": str(root / "manifest.json"),
                        "MEDKGI_KG_PATH": str(root / "primekg.json"),
                        "MEDKGI_PUBMEDBERT_MODEL": str(model_directory),
                    }
                )

        self.assertIsNotNone(strategy.core.aligner.embedder)
        self.assertIsNone(strategy.core.aligner.align("Duplicate display", "disease"))

    def test_from_environment_uses_exact_paths_and_rejects_remote_models(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "custom-manifest.json"
            graph_path = root / "custom-graph.json"
            embeddings_path = root / "custom-embeddings.npz"
            manifest_path.write_text(
                json.dumps({"artifacts": {"embeddings": {"path": embeddings_path.name}}}),
                encoding="utf-8",
            )
            with patch(
                "amie.medkgi_strategy.MedKGILoader.load",
                return_value=self.graph,
            ) as loader:
                strategy = MedKGIDiagnosisStrategy.from_environment(
                    {
                        "MEDKGI_MANIFEST_PATH": str(manifest_path),
                        "MEDKGI_KG_PATH": str(graph_path),
                        "MEDKGI_MAX_TURNS": "7",
                    }
                )

            loader.assert_called_once_with(graph_path, manifest_path, embeddings_path)
            self.assertEqual(strategy.core.config.turn_limit, 7)
            self.assertIsNone(strategy.core.aligner.embedder)

        with self.assertRaisesRegex(MedKGIStrategyError, "not hf://"):
            MedKGIDiagnosisStrategy.from_environment(
                {"MEDKGI_PUBMEDBERT_MODEL": "hf://example/pubmedbert"}
            )
        with self.assertRaisesRegex(MedKGIStrategyError, "existing local"):
            MedKGIDiagnosisStrategy.from_environment(
                {"MEDKGI_PUBMEDBERT_MODEL": "/definitely/missing/pubmedbert"}
            )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_directory = root / "model"
            model_directory.mkdir()
            with patch(
                "amie.medkgi_strategy.MedKGILoader.load",
                return_value=self.graph,
            ):
                with self.assertRaisesRegex(
                    MedKGIStrategyError, "manifest-verified node embeddings"
                ):
                    MedKGIDiagnosisStrategy.from_environment(
                        {
                            "MEDKGI_MANIFEST_PATH": str(root / "manifest.json"),
                            "MEDKGI_KG_PATH": str(root / "primekg.json"),
                            "MEDKGI_PUBMEDBERT_MODEL": str(model_directory),
                        }
                    )


if __name__ == "__main__":
    unittest.main()
