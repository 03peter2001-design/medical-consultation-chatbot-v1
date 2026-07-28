import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from knowledge.common import TAXONOMY_PATH
from scripts.classify_chunks import (
    _write_outputs,
    classify_chunk,
    load_taxonomy,
)


class ChunkClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.taxonomy = load_taxonomy()

    def classify(self, title, text, semantic_scores=None):
        return classify_chunk(
            {"title": title, "text": text},
            self.taxonomy,
            semantic_scores,
        )

    def test_typical_symptom_routes(self):
        cases = (
            (
                "Myocardial Infarction",
                "Acute coronary syndrome with chest pain.",
                "chest",
            ),
            ("Migraine", "Severe headache with photophobia.", "headache"),
            (
                "Appendicitis",
                "Right lower quadrant abdominal pain.",
                "abdomen",
            ),
        )
        for title, text, expected in cases:
            with self.subTest(expected=expected):
                result = self.classify(title, text)
                self.assertEqual(result.primary_route, expected)
                self.assertIn(expected, result.routes)

    def test_cross_system_chunk_is_multilabel(self):
        result = self.classify(
            "Chest and Abdominal Pain",
            "Chest pain may accompany abdominal pain in aortic disease.",
            semantic_scores={"chest": 1.0, "abdomen": 1.0},
        )
        self.assertIn("chest", result.routes)
        self.assertIn("abdomen", result.routes)

    def test_unrelated_content_is_archived(self):
        result = self.classify(
            "Benign Skin Lesion",
            "A superficial dermatologic lesion without systemic symptoms.",
        )
        self.assertEqual(result.primary_route, "archive")
        self.assertEqual(result.routes, ["archive"])

    def test_safety_requires_explicit_rule_match(self):
        result = self.classify(
            "Chest Discomfort",
            "Stable mild chest discomfort.",
            semantic_scores={"chest": 0.9, "common": 0.2},
        )
        self.assertNotIn("safety", result.routes)
        self.assertEqual(result.safety_tags, [])

        dangerous = self.classify(
            "Aortic Dissection",
            "Sudden tearing chest pain caused by aortic dissection.",
        )
        self.assertIn("safety", dangerous.routes)
        self.assertEqual(dangerous.route_scores["safety"], 1.0)
        self.assertIn("safety_candidate", dangerous.review_reasons)

    def test_writes_embedding_only_for_indexed_chunks(self):
        base = {
            "article_id": "article",
            "title": "Title",
            "url": "https://example.test/article",
            "updated": "Jan 1, 2026",
            "source_tags": ["test"],
            "source_labels": ["Test"],
            "route_scores": {
                "chest": 1.0,
                "headache": 0.0,
                "abdomen": 0.0,
                "common": 0.0,
                "safety": 0.0,
            },
            "clinical_stage": "general",
            "safety_tags": [],
            "classification_method": "embedding",
            "review_required": False,
            "review_reasons": [],
        }
        records = [
            {
                **base,
                "chunk_id": "indexed",
                "text": "chest pain content",
                "primary_route": "chest",
                "routes": ["chest"],
                "_embedding": np.asarray([1.0, 2.0, 3.0]),
            },
            {
                **base,
                "chunk_id": "archive",
                "text": "unrelated content",
                "primary_route": "archive",
                "routes": ["archive"],
                "classification_method": "archive",
                "_embedding": np.asarray([4.0, 5.0, 6.0]),
            },
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            output = directory / "classified_chunks.jsonl"
            embeddings = directory / "classified_embeddings.f32"
            report_path = directory / "classification_report.json"
            review = directory / "review_queue.csv"
            report = _write_outputs(
                records,
                output,
                embeddings,
                report_path,
                review,
                TAXONOMY_PATH,
            )
            written = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            embedding_size = embeddings.stat().st_size

        self.assertEqual(report["embedding_count"], 1)
        self.assertEqual(report["embedding_dimension"], 3)
        self.assertEqual(embedding_size, 3 * 4)
        self.assertEqual(written[0]["embedding_index"], 0)
        self.assertNotIn("embedding_index", written[1])


if __name__ == "__main__":
    unittest.main()
