import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chromadb

import rag
from ingest import (
    LEGACY_COLLECTION,
    attach_embeddings,
    build_collections,
    load_embedding_store,
)
from rag_common import INDEX_ROUTES, collection_name


class FakeEmbeddingFunction:
    def __call__(self, input):
        vectors = []
        for text in input:
            checksum = sum(ord(char) for char in text)
            vectors.append(
                [
                    float((checksum % 97) + 1),
                    float((len(text) % 89) + 1),
                    1.0,
                ]
            )
        return vectors

    def embed_query(self, input):
        return self(input)

    def embed_documents(self, input):
        return self(input)

    @staticmethod
    def is_legacy():
        return False

    @staticmethod
    def name():
        return "test-fake-embedding"


def record(chunk_id, routes):
    return {
        "chunk_id": chunk_id,
        "article_id": f"article-{chunk_id}",
        "text": f"medical content {chunk_id}",
        "title": f"Title {chunk_id}",
        "url": f"https://example.test/{chunk_id}",
        "updated": "Jan 1, 2026",
        "source_labels": ["Test"],
        "source_tags": ["test"],
        "routes": routes,
        "primary_route": routes[0],
        "route_scores": {route: 1.0 for route in routes},
        "clinical_stage": "general",
        "safety_tags": ["test"] if "safety" in routes else [],
        "classification_method": "rule",
    }


class IngestCollectionTests(unittest.TestCase):
    def setUp(self):
        self.client = chromadb.EphemeralClient()
        for item in self.client.list_collections():
            name = item.name if hasattr(item, "name") else str(item)
            self.client.delete_collection(name)

    def test_builds_five_collections_without_touching_legacy(self):
        client = self.client
        embedding = FakeEmbeddingFunction()
        legacy = client.create_collection(
            LEGACY_COLLECTION,
            embedding_function=embedding,
        )
        legacy.add(
            documents=["legacy document"],
            ids=["legacy-1"],
        )

        records = [
            record("chest-1", ["chest", "safety"]),
            record("head-1", ["headache"]),
            record("abdomen-1", ["abdomen"]),
            record("common-1", ["common"]),
        ]
        result = build_collections(
            client,
            records,
            version="v2test",
            embedding_function=embedding,
        )

        names = {
            item.name if hasattr(item, "name") else str(item)
            for item in client.list_collections()
        }
        self.assertIn(LEGACY_COLLECTION, names)
        self.assertEqual(
            client.get_collection(LEGACY_COLLECTION).count(),
            1,
        )
        for route in INDEX_ROUTES:
            self.assertIn(collection_name("v2test", route), names)
        self.assertEqual(result["vector_rows"], 5)

    def test_v2_retrieval_queries_routed_collections(self):
        client = self.client
        embedding = FakeEmbeddingFunction()
        client.create_collection(
            LEGACY_COLLECTION,
            embedding_function=embedding,
        )
        build_collections(
            client,
            [
                record("chest-1", ["chest", "safety"]),
                record("common-1", ["common"]),
            ],
            version="v2test",
            embedding_function=embedding,
        )
        registry = rag.CollectionRegistry(Path("/tmp/not-used"))
        registry._client = client
        registry._embedding_function = embedding

        with (
            patch.object(rag, "_registry", registry),
            patch.object(rag, "RAG_INDEX_VERSION", "v2test"),
            patch.object(rag, "DISTANCE_THRESHOLD", 2.0),
        ):
            results = rag.retrieve(
                "chest pain",
                primary_route="chest",
                final_k=6,
            )

        self.assertTrue(results)
        self.assertEqual(results[0]["chunk_id"], "chest-1")
        self.assertEqual(set(results[0]["routes"]), {"chest", "safety"})

    def test_loads_precomputed_embedding_store(self):
        import numpy as np

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            embeddings_path = directory / "classified_embeddings.f32"
            report_path = directory / "classification_report.json"
            np.asarray(
                [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
                dtype=np.float32,
            ).tofile(embeddings_path)
            report_path.write_text(
                json.dumps(
                    {
                        "embedding_count": 2,
                        "embedding_dimension": 3,
                        "embedding_model": rag.EMBEDDING_MODEL,
                    }
                ),
                encoding="utf-8",
            )
            store = load_embedding_store(
                embeddings_path,
                report_path,
            )
            records = list(
                attach_embeddings(
                    [
                        {"chunk_id": "c1", "embedding_index": 1},
                        {"chunk_id": "archive"},
                    ],
                    store,
                )
            )

        self.assertEqual(records[0]["_embedding"].tolist(), [4.0, 5.0, 6.0])
        self.assertNotIn("_embedding", records[1])

    def test_build_accepts_precomputed_embeddings(self):
        import numpy as np

        embedding = FakeEmbeddingFunction()
        records = [
            {
                **record("chest-precomputed", ["chest", "safety"]),
                "_embedding": np.asarray(
                    [1.0, 2.0, 3.0],
                    dtype=np.float32,
                ),
            }
        ]
        result = build_collections(
            self.client,
            records,
            version="v2precomputed",
            embedding_function=embedding,
        )
        self.assertEqual(result["vector_rows"], 2)
        self.assertEqual(
            self.client.get_collection(
                collection_name("v2precomputed", "chest")
            ).count(),
            1,
        )


if __name__ == "__main__":
    unittest.main()
