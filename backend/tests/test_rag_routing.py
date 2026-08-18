import unittest
from types import SimpleNamespace
from unittest.mock import patch

from knowledge import retrieval as rag
from knowledge.retrieval import (
    _expand_query_terms,
    _rrf_merge,
    select_routes,
)
from knowledge.translation import QueryNormalization


class RagRoutingTests(unittest.TestCase):
    def test_stage_scoped_query_uses_chroma_metadata_filter(self):
        class Collection:
            def __init__(self):
                self.query_kwargs = None

            def count(self):
                return 10

            def query(self, **kwargs):
                self.query_kwargs = kwargs
                return {
                    "documents": [["lab evidence"]],
                    "metadatas": [
                        [
                            {
                                "source": "synthetic",
                                "title": "Lab",
                                "clinical_stage": "lab",
                            }
                        ]
                    ],
                    "distances": [[0.1]],
                }

        collection = Collection()
        registry = SimpleNamespace(get=lambda **_kwargs: collection)
        with patch.object(rag, "_registry", registry):
            results, _ = rag._query_collection(
                "common",
                "troponin",
                clinical_stages=("lab",),
            )

        self.assertEqual(collection.query_kwargs["where"], {"clinical_stage": "lab"})
        self.assertEqual(results[0]["clinical_stage"], "lab")

    def test_knowledge_base_stage_mapping_is_explicit(self):
        self.assertEqual(rag.PURPOSE_CLINICAL_STAGES["diagnosis"], ("diagnosis", "workup"))
        self.assertEqual(rag.PURPOSE_CLINICAL_STAGES["lab"], ("lab",))
        self.assertEqual(rag.PURPOSE_CLINICAL_STAGES["imaging"], ("imaging",))

    def test_primary_route_always_includes_safety(self):
        routes = select_routes(
            "胸痛且想做抽血",
            primary_route="chest",
            purpose="lab",
        )
        self.assertEqual(routes[0], "chest")
        self.assertIn("common", routes)
        self.assertEqual(routes[-1], "safety")
        self.assertLessEqual(len(routes), 3)

    def test_free_query_selects_at_most_two_content_routes(self):
        routes = select_routes(
            "胸痛合併腹痛",
            semantic_scores={"chest": 0.8, "abdomen": 0.75},
        )
        self.assertIn("chest", routes)
        self.assertIn("abdomen", routes)
        self.assertEqual(routes[-1], "safety")
        self.assertLessEqual(len(routes), 3)

    def test_uncertain_query_uses_common_and_safety(self):
        routes = select_routes("請提供一般資訊", semantic_scores={})
        self.assertEqual(routes, ["common", "safety"])

    def test_red_flag_query_expansion_is_deterministic(self):
        self.assertIn(
            "subarachnoid hemorrhage",
            _expand_query_terms("人生最嚴重的雷擊樣頭痛"),
        )
        self.assertIn(
            "ectopic pregnancy",
            _expand_query_terms("腹痛昏厥且月經過期"),
        )

    def test_rrf_deduplicates_chunks_and_limits_article_chunks(self):
        def item(chunk_id, article_id, route, rank, distance):
            return {
                "chunk_id": chunk_id,
                "article_id": article_id,
                "route": route,
                "rank": rank,
                "distance": distance,
                "text": chunk_id,
                "source": "source",
                "title": article_id,
                "url": f"https://example.test/{article_id}",
            }

        merged = _rrf_merge(
            [
                [
                    item("c1", "a1", "chest", 1, 0.1),
                    item("c2", "a1", "chest", 2, 0.2),
                    item("c3", "a1", "chest", 3, 0.3),
                ],
                [
                    item("c1", "a1", "safety", 1, 0.15),
                    item("c4", "a2", "safety", 2, 0.2),
                ],
            ],
            final_k=6,
        )
        self.assertEqual(sum(x["chunk_id"] == "c1" for x in merged), 1)
        self.assertEqual(sum(x["article_id"] == "a1" for x in merged), 2)
        c1 = next(x for x in merged if x["chunk_id"] == "c1")
        self.assertEqual(set(c1["routes"]), {"chest", "safety"})

    def test_empty_v2_results_fall_back_to_legacy(self):
        legacy_result = {
            "chunk_id": "legacy-1",
            "article_id": "legacy-article",
            "route": "legacy",
            "distance": 0.2,
            "text": "legacy content",
            "source": "legacy",
            "title": "Legacy",
            "url": "https://example.test/legacy",
        }
        registry = SimpleNamespace(embedding_function=lambda input: [[0.0, 0.0, 0.0]])
        with (
            patch.object(rag, "RAG_INDEX_VERSION", "v2"),
            patch.object(rag, "_registry", registry),
            patch.object(
                rag,
                "_query_collection",
                return_value=([], 0.001),
            ),
            patch.object(
                rag,
                "get_rag_status",
                return_value={
                    "enabled": True,
                    "index_version": "v2",
                    "collections": ["chest", "safety"],
                    "legacy_available": True,
                },
            ),
            patch.object(
                rag,
                "_legacy_retrieve",
                return_value=[legacy_result],
            ) as legacy,
        ):
            results = rag.retrieve(
                "胸痛",
                primary_route="chest",
                final_k=6,
            )

        self.assertEqual(results, [legacy_result])
        legacy.assert_called_once()

    def test_dual_query_batches_original_and_english_embeddings(self):
        normalized = QueryNormalization(
            literal_translation=("Unilateral pulsating headache with photophobia and nausea."),
            positive_findings=(
                "unilateral pulsating headache",
                "photophobia",
                "nausea",
            ),
            negative_findings=(),
            uncertain_findings=(),
            temporality=(),
            standardized_terms=("unilateral pulsating headache",),
            retrieval_query=("unilateral pulsating headache photophobia nausea"),
        )
        normalizer = SimpleNamespace(
            query_mode="dual",
            normalize=lambda query: normalized,
        )
        embedded_inputs = []

        def embed(input):
            embedded_inputs.append(input)
            return [[0.1, 0.2], [0.2, 0.1]]

        registry = SimpleNamespace(embedding_function=embed)

        def batched(
            route,
            query_embeddings,
            query_variants,
            n_results,
            clinical_stages=None,
        ):
            self.assertIsNone(clinical_stages)

            def item(variant):
                return {
                    "chunk_id": f"{route}-1",
                    "article_id": f"{route}-article",
                    "route": route,
                    "rank": 1,
                    "distance": 0.1,
                    "text": f"{route} content",
                    "source": "source",
                    "title": f"{route} title",
                    "url": f"https://example.test/{route}",
                    "clinical_stage": "diagnosis",
                    "query_variant": variant,
                }

            return [
                [item("original")],
                [item("english")],
            ], 0.001

        with (
            patch.object(rag, "RAG_INDEX_VERSION", "v2"),
            patch.object(rag, "_registry", registry),
            patch.object(
                rag,
                "get_query_normalizer",
                return_value=normalizer,
            ),
            patch.object(
                rag,
                "_query_collection_variants",
                side_effect=batched,
            ) as query_batch,
        ):
            results = rag.retrieve(
                "單側跳痛伴隨畏光噁心",
                primary_route="headache",
                final_k=6,
            )

        self.assertEqual(len(embedded_inputs), 1)
        self.assertEqual(len(embedded_inputs[0]), 2)
        self.assertEqual(query_batch.call_count, 2)
        self.assertTrue(results)
        self.assertEqual(
            set(results[0]["query_variants"]),
            {"original", "english"},
        )


if __name__ == "__main__":
    unittest.main()
