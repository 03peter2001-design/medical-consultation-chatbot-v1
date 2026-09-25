import csv
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from scripts.build_medkgi_assets import (
    EMBEDDING_FILENAME,
    REQUIRED_COLUMNS,
    build_assets,
)


class MedKGIAssetBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.csv_path = self.root / "primekg.csv"
        self.output_dir = self.root / "output"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _write_rows(self, rows, columns=REQUIRED_COLUMNS):
        with self.csv_path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _row(**overrides):
        row = {
            "x_index": "1",
            "y_index": "2",
            "x_id": "MONDO:synthetic-a",
            "y_id": "HP:synthetic-a",
            "x_type": "disease",
            "y_type": "effect/phenotype",
            "x_name": "Synthetic condition A",
            "y_name": "Synthetic finding A",
            "relation": "associated_with",
            "display_relation": "phenotype present",
        }
        row.update(overrides)
        return row

    def test_filters_normalizes_and_deduplicates_supported_edges(self):
        rows = [
            self._row(),
            self._row(),
            self._row(
                x_index="3",
                y_index="1",
                x_id="HP:synthetic-b",
                y_id="MONDO:synthetic-a",
                x_type="symptom",
                y_type="disease",
                x_name="Synthetic finding B",
                y_name="Synthetic condition A",
            ),
            self._row(
                x_index="1",
                y_index="4",
                y_id="MONDO:synthetic-b",
                y_type="disease",
                y_name="Synthetic condition B",
                relation="parent_child",
                display_relation="parent-child",
            ),
            self._row(
                x_index="5",
                y_index="6",
                x_id="DRUG:synthetic",
                y_id="GENE:synthetic",
                x_type="drug",
                y_type="gene/protein",
                x_name="Synthetic compound",
                y_name="Synthetic target",
            ),
        ]
        self._write_rows(rows)
        embedding_writer = Mock(side_effect=AssertionError("embeddings must be opt-in"))
        manifest = build_assets(
            self.csv_path,
            self.output_dir,
            "synthetic-2026-01",
            generated_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
            embedding_writer=embedding_writer,
        )

        asset_path = self.output_dir / "primekg.json"
        asset = json.loads(asset_path.read_text(encoding="utf-8"))
        self.assertEqual([node["id"] for node in asset["nodes"]], [1, 2, 3, 4])
        self.assertEqual(
            [edge["kind"] for edge in asset["edges"]],
            ["disease_symptom", "disease_symptom", "disease_disease"],
        )
        self.assertEqual(asset["edges"][1]["source"], 1)
        self.assertEqual(asset["edges"][1]["target"], 3)
        self.assertEqual(asset["generated_at"], "2026-01-02T03:04:05Z")
        self.assertEqual(manifest["counts"]["input_rows"], 5)
        self.assertEqual(manifest["counts"]["skipped_rows"], 1)
        self.assertEqual(manifest["counts"]["duplicate_edges_removed"], 1)
        self.assertEqual(manifest["counts"]["disease_symptom_edges"], 2)
        self.assertEqual(manifest["counts"]["disease_disease_edges"], 1)
        self.assertEqual(
            manifest["source"]["sha256"], hashlib.sha256(self.csv_path.read_bytes()).hexdigest()
        )
        self.assertEqual(
            manifest["artifacts"]["primekg"]["sha256"],
            hashlib.sha256(asset_path.read_bytes()).hexdigest(),
        )
        embedding_writer.assert_not_called()
        self.assertFalse((self.output_dir / EMBEDDING_FILENAME).exists())

    def test_same_endpoint_pair_with_different_relations_is_deduplicated(self):
        self._write_rows(
            [
                self._row(relation="z_relation", display_relation="z display"),
                self._row(relation="a_relation", display_relation="a display"),
            ]
        )

        manifest = build_assets(self.csv_path, self.output_dir, "synthetic")
        asset = json.loads((self.output_dir / "primekg.json").read_text(encoding="utf-8"))

        self.assertEqual(len(asset["edges"]), 1)
        self.assertEqual(asset["edges"][0]["relation"], "a_relation")
        self.assertEqual(asset["edges"][0]["display_relation"], "a display")
        self.assertEqual(manifest["counts"]["duplicate_edges_removed"], 1)

    def test_rejects_missing_columns_without_publishing_outputs(self):
        columns = tuple(column for column in REQUIRED_COLUMNS if column != "display_relation")
        self._write_rows([], columns=columns)

        with self.assertRaisesRegex(ValueError, "missing required columns"):
            build_assets(self.csv_path, self.output_dir, "synthetic")

        self.assertFalse((self.output_dir / "primekg.json").exists())
        self.assertFalse((self.output_dir / "manifest.json").exists())

    def test_rejects_invalid_indexes_and_conflicting_node_metadata(self):
        for rows, message in (
            ([self._row(x_index="1.5")], "x_index must be an integer"),
            (
                [self._row(), self._row(x_name="Conflicting synthetic condition")],
                "conflicting metadata",
            ),
        ):
            with self.subTest(message=message):
                self._write_rows(rows)
                with self.assertRaisesRegex(ValueError, message):
                    build_assets(self.csv_path, self.output_dir, "synthetic")

    def test_rejects_csv_without_supported_edges(self):
        self._write_rows(
            [
                self._row(
                    x_type="drug",
                    y_type="gene/protein",
                    x_name="Synthetic compound",
                    y_name="Synthetic target",
                )
            ]
        )

        with self.assertRaisesRegex(ValueError, "no disease-symptom or disease-disease"):
            build_assets(self.csv_path, self.output_dir, "synthetic")

    def test_embedding_generation_is_explicit_and_recorded_in_manifest(self):
        self._write_rows([self._row()])

        def fake_writer(path, nodes, model_argument, batch_size):
            self.assertEqual(len(nodes), 2)
            self.assertEqual(model_argument, "hf://example/pubmedbert")
            self.assertEqual(batch_size, 7)
            path.write_bytes(b"synthetic-npz")
            return {
                "model": model_argument,
                "pooling": "attention-mask-mean",
                "normalized": True,
                "dimensions": 3,
                "node_count": len(nodes),
            }

        manifest = build_assets(
            self.csv_path,
            self.output_dir,
            "synthetic",
            embedding_model="hf://example/pubmedbert",
            embedding_batch_size=7,
            embedding_writer=fake_writer,
        )

        embedding_path = self.output_dir / EMBEDDING_FILENAME
        self.assertEqual(embedding_path.read_bytes(), b"synthetic-npz")
        self.assertEqual(manifest["artifacts"]["embeddings"]["dimensions"], 3)
        self.assertEqual(
            manifest["artifacts"]["embeddings"]["sha256"],
            hashlib.sha256(b"synthetic-npz").hexdigest(),
        )

    def test_existing_outputs_require_force(self):
        self._write_rows([self._row()])
        build_assets(self.csv_path, self.output_dir, "synthetic")

        with self.assertRaisesRegex(FileExistsError, "--force"):
            build_assets(self.csv_path, self.output_dir, "synthetic")


if __name__ == "__main__":
    unittest.main()
