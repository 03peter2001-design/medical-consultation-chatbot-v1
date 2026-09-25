import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from medkgi import (
    EntityAligner,
    KnowledgeGraph,
    MedKGIAssetError,
    MedKGIConfig,
    MedKGICore,
    MedKGILoader,
    MedKGIUnavailable,
)
from medkgi.inference import disease_posteriors, information_gain_candidates, shannon_entropy
from medkgi.models import OSCEState


def _graph() -> KnowledgeGraph:
    diseases = [
        {"id": "cold", "name": "Common cold", "aliases": ["viral cold"], "prior": 0.5},
        {"id": "flu", "name": "Influenza", "aliases": ["flu"], "prior": 0.3},
        {"id": "measles", "name": "Measles", "prior": 0.2},
        {"id": "d4", "name": "Disease Four"},
        {"id": "d5", "name": "Disease Five"},
        {"id": "d6", "name": "Disease Six"},
    ]
    symptoms = [
        {"id": "cough", "name": "Cough"},
        {"id": "fever", "name": "Fever", "aliases": ["pyrexia"]},
        {"id": "rash", "name": "Rash"},
        {"id": "aches", "name": "Body aches"},
        {"id": "alpha", "name": "Alpha sign"},
        {"id": "beta", "name": "Beta sign"},
    ]
    edges = [
        {"disease_id": "cold", "symptom_id": "cough", "probability": 0.8},
        {"disease_id": "cold", "symptom_id": "fever", "probability": 0.2},
        {"disease_id": "cold", "symptom_id": "alpha", "probability": 0.5},
        {"disease_id": "cold", "symptom_id": "beta", "probability": 0.5},
        {"disease_id": "flu", "symptom_id": "cough", "probability": 0.6},
        {"disease_id": "flu", "symptom_id": "fever", "probability": 0.9},
        {"disease_id": "flu", "symptom_id": "aches", "probability": 0.8},
        {"disease_id": "flu", "symptom_id": "alpha", "probability": 0.5},
        {"disease_id": "flu", "symptom_id": "beta", "probability": 0.5},
        {"disease_id": "measles", "symptom_id": "fever", "probability": 0.8},
        {"disease_id": "measles", "symptom_id": "rash", "probability": 0.95},
        {"disease_id": "d4", "symptom_id": "cough"},
        {"disease_id": "d5", "symptom_id": "fever"},
        {"disease_id": "d6", "symptom_id": "rash", "probability": 0.1},
    ]
    return KnowledgeGraph.from_records(
        version="synthetic-v1",
        diseases=diseases,
        symptoms=symptoms,
        edges=edges,
    )


class FakeEmbedder:
    def encode(self, texts):
        vectors = {
            "grippe": [1.0, 0.0],
            "Common cold": [0.0, 1.0],
            "Disease Five": [0.0, 0.2],
            "Disease Four": [0.0, 0.2],
            "Disease Six": [0.0, 0.2],
            "Influenza": [0.99, 0.01],
            "Measles": [0.0, 1.0],
            "unknown concept": [1.0, 0.0],
        }
        return [vectors[text] for text in texts]


class KnowledgeGraphLoadingTests(unittest.TestCase):
    def _write_assets(self, directory: Path, *, review_status="clinician_reviewed") -> Path:
        graph = {
            "schema_version": 1,
            "knowledge_graph_version": "reviewed-v1",
            "diseases": [{"id": "d1", "name": "Disease"}],
            "symptoms": [{"id": "s1", "name": "Symptom"}],
            "edges": [{"disease_id": "d1", "symptom_id": "s1", "probability": 0.7}],
        }
        graph_bytes = json.dumps(graph, sort_keys=True).encode()
        (directory / "graph.json").write_bytes(graph_bytes)
        manifest = {
            "schema_version": 1,
            "knowledge_graph_version": "reviewed-v1",
            "created_at": "2026-09-23",
            "graph_file": "graph.json",
            "graph_sha256": hashlib.sha256(graph_bytes).hexdigest(),
            "source": {
                "name": "Synthetic reviewed fixture",
                "uri": "https://example.invalid/source",
                "license": "test-license",
            },
            "review": {
                "status": review_status,
                "reviewer": "Test Clinician",
                "date": "2026-09-23",
            },
        }
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return directory

    def test_load_local_verifies_manifest_hash_and_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            graph = KnowledgeGraph.load_local(self._write_assets(Path(temp)))

        self.assertEqual(graph.provenance.knowledge_graph_version, "reviewed-v1")
        self.assertEqual(graph.provenance.review_status, "clinician_reviewed")
        self.assertEqual(graph.diseases["d1"].name, "Disease")

    def test_missing_unreviewed_and_tampered_assets_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(MedKGIAssetError, "manifest is missing"):
                KnowledgeGraph.load_local(temp)

        with tempfile.TemporaryDirectory() as temp:
            directory = self._write_assets(Path(temp), review_status="unreviewed")
            with self.assertRaisesRegex(MedKGIAssetError, "clinician_reviewed"):
                KnowledgeGraph.load_local(directory)

        with tempfile.TemporaryDirectory() as temp:
            directory = self._write_assets(Path(temp))
            (directory / "graph.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(MedKGIAssetError, "hash"):
                KnowledgeGraph.load_local(directory)

    def test_builder_format_loads_orphans_and_validates_embedding_node_order(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source_hash = "a" * 64
            graph_document = {
                "schema_version": 1,
                "source": {"version": "primekg-v1", "sha256": source_hash},
                "generated_at": "2026-09-23T00:00:00Z",
                "nodes": [
                    {"id": 1, "name": "Duplicate disease", "kind": "disease"},
                    {"id": 2, "name": "Duplicate disease", "kind": "disease"},
                    {"id": 3, "name": "Finding", "kind": "symptom"},
                ],
                "edges": [
                    {"source": 1, "target": 3, "kind": "disease_symptom"},
                    {"source": 1, "target": 2, "kind": "disease_disease"},
                ],
            }
            graph_bytes = json.dumps(graph_document, sort_keys=True).encode()
            graph_path = directory / "primekg.json"
            graph_path.write_bytes(graph_bytes)
            embedding_path = directory / "pubmedbert_embeddings.npz"
            np.savez(
                embedding_path,
                node_ids=np.array([1, 2, 3], dtype=np.int64),
                embeddings=np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]], dtype=np.float32),
            )
            embedding_bytes = embedding_path.read_bytes()
            manifest = {
                "artifact_kind": "medkgi_primekg_assets",
                "schema_version": 1,
                "generated_at": "2026-09-23T00:00:00Z",
                "source": {
                    "path": "/synthetic/primekg.csv",
                    "version": "primekg-v1",
                    "sha256": source_hash,
                },
                "artifacts": {
                    "primekg": {
                        "path": graph_path.name,
                        "sha256": hashlib.sha256(graph_bytes).hexdigest(),
                    },
                    "embeddings": {
                        "path": embedding_path.name,
                        "sha256": hashlib.sha256(embedding_bytes).hexdigest(),
                        "model": "synthetic-pubmedbert",
                        "dimensions": 2,
                        "node_count": 3,
                    },
                },
            }
            manifest_path = directory / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            graph = MedKGILoader.load(graph_path, manifest_path, embedding_path)
            self.assertEqual(set(graph.diseases), {"1", "2"})
            self.assertEqual(tuple(graph.symptoms), ("3",))
            self.assertEqual(len(graph.edges), 1)
            self.assertEqual(graph.provenance.review_status, "research_unreviewed")
            self.assertEqual(graph.node_embeddings["1"], (1.0, 0.0))
            self.assertIsNone(EntityAligner(graph).align("Duplicate disease", "disease"))
            orphan = MedKGICore(graph).assess(OSCEState(), candidate_ids=("2",))
            self.assertEqual(orphan.decision.action, "handoff")
            self.assertEqual(orphan.unmatched_terms, ("2",))
            self.assertEqual(KnowledgeGraph.load_local(directory).provenance, graph.provenance)

            np.savez(
                embedding_path,
                node_ids=np.array([2, 1, 3], dtype=np.int64),
                embeddings=np.ones((3, 2), dtype=np.float32),
            )
            manifest["artifacts"]["embeddings"]["sha256"] = hashlib.sha256(
                embedding_path.read_bytes()
            ).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(MedKGIUnavailable, "node_ids"):
                MedKGILoader.load(graph_path, manifest_path, embedding_path)

    def test_invalid_graph_references_and_ambiguous_labels_fail_closed(self):
        with self.assertRaisesRegex(MedKGIAssetError, "unknown entity"):
            KnowledgeGraph.from_records(
                version="bad",
                diseases=[{"id": "d1", "name": "Disease"}],
                symptoms=[{"id": "s1", "name": "Symptom"}],
                edges=[{"disease_id": "d1", "symptom_id": "missing"}],
            )
        graph = KnowledgeGraph.from_records(
            version="ambiguous",
            diseases=[
                {"id": "d1", "name": "Disease"},
                {"id": "d2", "name": "Other", "aliases": ["disease"]},
            ],
            symptoms=[{"id": "s1", "name": "Symptom"}],
            edges=[
                {"disease_id": "d1", "symptom_id": "s1"},
                {"disease_id": "d2", "symptom_id": "s1"},
            ],
        )
        self.assertIsNone(EntityAligner(graph).align("disease", "disease"))


class EntityAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.graph = _graph()

    def test_exact_alias_and_edit_distance_alignment(self):
        aligner = EntityAligner(self.graph)

        exact = aligner.align("  FLU ", "disease")
        alias = aligner.align("ＰＹＲＥＸＩＡ", "symptom")
        edit = aligner.align("Influenz", "disease")
        missing = aligner.align("completely unrelated phrase", "disease")

        self.assertEqual((exact.entity_id, exact.method), ("flu", "exact"))
        self.assertEqual((alias.entity_id, alias.method), ("fever", "exact"))
        self.assertEqual((edit.entity_id, edit.method, edit.score), ("flu", "edit_distance", 1.0))
        self.assertIsNone(missing)

    def test_ontology_label_cleanup_and_safe_edit_distance_gate(self):
        graph = KnowledgeGraph.from_records(
            version="alignment-safety",
            diseases=[
                {"id": "acs", "name": "ACS - Acute coronary syndrome (disorder)"},
                {"id": "pe", "name": "PE - Pulmonary embolism (disease)"},
                {"id": "gi", "name": "Gastrointestinal bleeding"},
                {"id": "short", "name": "mo"},
                {"id": "zh-near", "name": "氣胸症"},
                {"id": "zh-exact", "name": "肺炎"},
            ],
            symptoms=[{"id": "s1", "name": "Synthetic finding"}],
            edges=[
                {"disease_id": disease_id, "symptom_id": "s1"}
                for disease_id in ("acs", "pe", "gi", "short", "zh-near", "zh-exact")
            ],
        )
        aligner = EntityAligner(graph)

        self.assertEqual(aligner.align("Acute coronary syndrome", "disease").entity_id, "acs")
        self.assertEqual(aligner.align("Pulmonary embolism", "disease").entity_id, "pe")
        self.assertEqual(
            aligner.align("GI - Gastrointestinal bleeding (finding)", "disease").entity_id,
            "gi",
        )
        self.assertEqual(aligner.align("肺炎", "disease").entity_id, "zh-exact")
        self.assertIsNone(aligner.align("氣胸", "disease"))
        self.assertIsNone(aligner.align("moo", "disease"))

    def test_optional_embedding_alignment_uses_threshold_and_deterministic_ties(self):
        aligner = EntityAligner(self.graph, embedder=FakeEmbedder(), semantic_threshold=0.85)

        match = aligner.align("grippe", "disease")
        tied = aligner.align("unknown concept", "disease")

        self.assertEqual((match.entity_id, match.method), ("flu", "embedding"))
        self.assertEqual(tied.entity_id, "flu")
        rejecting = EntityAligner(self.graph, embedder=FakeEmbedder(), semantic_threshold=1.0)
        self.assertIsNone(rejecting.align("grippe", "disease"))
        self.assertIsNone(aligner.align("氣胸", "disease"))

    def test_precomputed_embeddings_encode_only_query_and_require_complete_nodes(self):
        class QueryEmbedder:
            def __init__(self):
                self.calls = []

            def encode(self, texts):
                self.calls.append(tuple(texts))
                return [[1.0, 0.0]]

        embeddings = {
            disease_id: ((1.0, 0.0) if disease_id == "flu" else (0.0, 1.0))
            for disease_id in self.graph.diseases
        }
        graph = KnowledgeGraph(
            self.graph.provenance,
            self.graph.diseases,
            self.graph.symptoms,
            self.graph.edges,
            node_embeddings=embeddings,
        )
        embedder = QueryEmbedder()
        match = EntityAligner(graph, embedder=embedder).align("zxqvbnm", "disease")

        self.assertEqual(match.entity_id, "flu")
        self.assertEqual(embedder.calls, [("zxqvbnm",)])

        incomplete = KnowledgeGraph(
            self.graph.provenance,
            self.graph.diseases,
            self.graph.symptoms,
            self.graph.edges,
            node_embeddings={"flu": (1.0, 0.0)},
        )
        with self.assertRaisesRegex(MedKGIAssetError, "incomplete"):
            EntityAligner(incomplete, embedder=QueryEmbedder()).align("zxqvbnm", "disease")


class MedKGIInferenceTests(unittest.TestCase):
    def setUp(self):
        self.graph = _graph()

    def test_osce_state_tracks_and_revises_structured_evidence(self):
        state = OSCEState(
            demographics=(("age", "30"),),
            chief_complaint="fever",
            medical_history=("asthma",),
            examinations=("temperature 38 C",),
        )
        state = state.with_observation("fever", "positive", source_text="I have fever")
        revised = state.with_observation("fever", "negative", source_text="No measured fever")

        self.assertEqual(revised.positive_symptom_ids, ())
        self.assertEqual(revised.negative_symptom_ids, ("fever",))
        self.assertEqual(revised.evidence[0].source_text, "No measured fever")
        self.assertEqual(revised.demographics, (("age", "30"),))

    def test_bayesian_posterior_is_smoothed_normalized_and_evidence_grounded(self):
        state = OSCEState().with_observation("rash", "positive")
        posterior = disease_posteriors(
            self.graph,
            ("cold", "flu", "measles"),
            state,
            smoothing=1e-6,
        )

        self.assertEqual(posterior[0].disease_id, "measles")
        self.assertAlmostEqual(sum(item.probability for item in posterior), 1.0)
        self.assertTrue(all(item.probability > 0 for item in posterior))
        self.assertEqual(posterior[0].supporting_symptom_ids, ("rash",))

    def test_entropy_and_information_gain_exclude_observed_and_asked_symptoms(self):
        self.assertAlmostEqual(shannon_entropy((0.5, 0.5)), math.log(2))
        state = OSCEState().with_observation("fever", "positive").with_inquiry("cough")
        posterior = disease_posteriors(
            self.graph,
            ("cold", "flu"),
            state,
            smoothing=1e-6,
        )
        inquiries = information_gain_candidates(
            self.graph,
            posterior,
            state,
            smoothing=1e-6,
        )

        ids = [item.symptom_id for item in inquiries]
        self.assertNotIn("fever", ids)
        self.assertNotIn("cough", ids)
        self.assertEqual(ids[-2:], ["alpha", "beta"])
        self.assertAlmostEqual(inquiries[-2].information_gain, inquiries[-1].information_gain)

    def test_invalid_probability_inputs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "sum to one"):
            shannon_entropy((0.2, 0.2))
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            disease_posteriors(
                self.graph,
                ("cold", "flu"),
                OSCEState(),
                smoothing=1e-6,
                prior_weights={"cold": -1, "flu": 1},
            )


class MedKGICoreDecisionTests(unittest.TestCase):
    def setUp(self):
        self.graph = _graph()

    def test_core_caps_candidates_at_five_and_records_provenance(self):
        core = MedKGICore(self.graph)
        result = core.assess(
            OSCEState(),
            candidate_ids=("cold", "flu", "measles", "d4", "d5", "d6"),
        )

        self.assertEqual(len(result.candidates), 5)
        self.assertEqual(result.provenance.knowledge_graph_version, "synthetic-v1")
        self.assertEqual(result.provenance.review_status, "synthetic_unreviewed")

    def test_evidence_supported_sixth_candidate_can_rank_into_top_five(self):
        state = OSCEState().with_observation("rash", "positive")
        result = MedKGICore(self.graph).assess(
            state,
            candidate_ids=("cold", "flu", "d4", "d5", "measles", "d6"),
        )

        self.assertEqual(len(result.candidates), 5)
        self.assertIn("d6", {item.disease_id for item in result.candidates})
        self.assertAlmostEqual(sum(item.probability for item in result.candidates), 1.0)

    def test_approved_query_allowlist_filters_inquiries_and_fails_on_unknown_ids(self):
        core = MedKGICore(self.graph)
        result = core.assess(
            OSCEState(),
            candidate_ids=("cold", "flu"),
            approved_query_symptom_ids=("aches",),
        )

        self.assertEqual([item.symptom_id for item in result.inquiries], ["aches"])
        self.assertEqual(result.decision.next_symptom_id, "aches")
        with self.assertRaisesRegex(ValueError, "not in the graph"):
            core.assess(
                OSCEState(),
                candidate_ids=("cold", "flu"),
                approved_query_symptom_ids=("unknown",),
            )

    def test_core_aligns_terms_reports_unmatched_and_asks_maximum_gain_question(self):
        core = MedKGICore(self.graph)
        result = core.assess(
            OSCEState(chief_complaint="fever"),
            candidate_terms=("flu", "Common cold", "not in graph"),
        )

        self.assertEqual(result.decision.action, "inquire")
        self.assertEqual(result.decision.reason, "maximum_information_gain")
        self.assertEqual(result.state.turn_count, 0)
        self.assertNotIn(result.decision.next_symptom_id, result.state.asked_symptom_ids)
        self.assertEqual(result.unmatched_terms, ("not in graph",))
        self.assertEqual([item.method for item in result.alignments], ["exact", "exact"])

    def test_positive_evidence_can_generate_grounded_candidates(self):
        state = OSCEState().with_observation("rash", "positive")
        result = MedKGICore(self.graph).assess(state)

        self.assertEqual(result.candidates[0].disease_id, "measles")
        self.assertTrue(all(item.disease_id in {"measles", "d6"} for item in result.candidates))

    def test_missing_candidates_fail_closed_to_handoff(self):
        result = MedKGICore(self.graph).assess(
            OSCEState(),
            candidate_terms=("not in graph",),
        )

        self.assertEqual(result.decision.action, "handoff")
        self.assertEqual(result.decision.reason, "no_kg_grounded_candidates")
        self.assertEqual(result.candidates, ())

    def test_turn_limit_forces_final_decision_without_another_question(self):
        core = MedKGICore(self.graph, config=MedKGIConfig(turn_limit=2))
        result = core.assess(
            OSCEState(turn_count=2),
            candidate_ids=("cold", "flu"),
        )

        self.assertEqual(result.decision.action, "final")
        self.assertEqual(result.decision.reason, "turn_limit")
        self.assertEqual(result.state.turn_count, 2)

    def test_stagnation_seeks_refuting_evidence_then_finalizes_when_none_exists(self):
        snapshot = tuple(sorted(("cold", "flu")))
        stagnant = OSCEState(candidate_history=(snapshot, snapshot))
        core = MedKGICore(self.graph, config=MedKGIConfig(stagnation_turns=2))
        result = core.assess(stagnant, candidate_ids=("cold", "flu"))

        self.assertEqual(result.decision.action, "inquire")
        self.assertEqual(result.decision.reason, "stagnation_refutation")
        self.assertGreater(
            next(
                item.refutation_margin
                for item in result.inquiries
                if item.symptom_id == result.decision.next_symptom_id
            ),
            0,
        )

        exhausted = OSCEState(
            asked_symptom_ids=tuple(self.graph.symptoms),
            candidate_history=(snapshot, snapshot),
        )
        final = core.assess(exhausted, candidate_ids=("cold", "flu"))
        self.assertEqual(final.decision.action, "final")
        self.assertEqual(final.decision.reason, "stagnation_no_refuting_symptom")

    def test_no_information_gain_finalizes_with_deterministic_reason(self):
        core = MedKGICore(
            self.graph,
            config=MedKGIConfig(minimum_information_gain=10.0),
        )
        result = core.assess(OSCEState(), candidate_ids=("cold", "flu"))

        self.assertEqual(result.decision.action, "final")
        self.assertEqual(result.decision.reason, "no_information_gain")


if __name__ == "__main__":
    unittest.main()
