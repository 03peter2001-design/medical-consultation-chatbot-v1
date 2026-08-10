from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from domain.questionnaires import CANDIDATE_DISEASE_ROUTES, DISEASE_ROUTES
from scripts.amie_route_draft_schema import validate_proposal
from scripts.build_amie_route_drafts import (
    _failed_route_level_output,
    _namespace_candidate_codes,
    _normalize_discovery_citations,
    _normalize_focused_output,
    build_route,
)


def _prompt_json(prompt: str, marker: str) -> object:
    return json.loads(prompt.split(marker, 1)[1].splitlines()[0])


class _FakeGemini:
    provider = "gemini"
    model = "gemini-test"

    def __init__(self) -> None:
        self.calls = 0

    def generate_text(self, messages, *, temperature: float, max_tokens: int) -> str:
        self.calls += 1
        prompt = messages[-1]["content"]
        if self.calls == 1:
            sources = _prompt_json(prompt, "INITIAL_RAG_SOURCES: ")
            return json.dumps(
                {
                    "route": "weakness",
                    "evidence_status": "limited",
                    "diseases": [
                        {
                            "id": "weakness__myasthenia_gravis",
                            "name": "Myasthenia gravis",
                            "rationale": "Synthetic test evidence only.",
                            "source_ids": [sources[0]["id"]],
                        }
                    ],
                    "review_notes": [],
                }
            )
        sources = _prompt_json(prompt, "RAG_SOURCES: ")
        disease_source = next(
            item for item in sources if "weakness__myasthenia_gravis" in item["retrieval_scopes"]
        )
        source_id = disease_source["id"]
        query = _prompt_json(prompt, "DISCOVERED_DISEASES_AND_FIXED_QUERIES: ")[0][
            "retrieval_query"
        ]
        return json.dumps(
            {
                "route": "weakness",
                "evidence_status": "limited",
                "route_review": {
                    "recommended_disposition": "questionnaire",
                    "recommended_clinical_domain": None,
                    "rationale": "Synthetic test evidence only.",
                    "source_ids": [source_id],
                },
                "fact_proposals": [
                    {
                        "code": "weakness__myasthenia_gravis__generalized_weakness",
                        "description": "Synthetic generalized weakness fact.",
                        "kind": "symptom",
                        "safety_candidate": False,
                        "disease_ids": ["weakness__myasthenia_gravis"],
                        "source_ids": [source_id],
                    }
                ],
                "semantic_options": [
                    {
                        "field": "location_of_weakness",
                        "option": "全身無力",
                        "mapping": {
                            "findings": ["weakness__myasthenia_gravis__generalized_weakness"]
                        },
                        "disease_ids": ["weakness__myasthenia_gravis"],
                        "source_ids": [source_id],
                    }
                ],
                "profile_status": "proposed",
                "profiles": [
                    {
                        "id": "weakness__myasthenia_gravis",
                        "name": "Myasthenia gravis",
                        "must_not_miss": False,
                        "retrieval_query": query,
                        "safety_rule_codes": [],
                        "clues": [
                            {
                                "fact": "weakness__myasthenia_gravis__generalized_weakness",
                                "status": "present",
                                "direction": "support",
                                "weight": 1,
                                "source_ids": [source_id],
                            }
                        ],
                        "source_ids": [source_id],
                    }
                ],
                "safety_proposals": [],
                "unsupported_requirements": [],
                "review_notes": [],
            }
        )


class AmieRouteDraftPipelineTests(unittest.TestCase):
    def test_disease_name_drives_second_stage_rag_and_semantic_trace(self) -> None:
        rag_queries: list[str] = []

        def retrieve(query: str, **_: object) -> list[dict[str, object]]:
            rag_queries.append(query)
            is_disease = query.startswith("Myasthenia gravis ")
            return [
                {
                    "text": (
                        "Synthetic disease-name evidence about fatigable weakness."
                        if is_disease
                        else "Synthetic route evidence naming Myasthenia gravis."
                    ),
                    "source": "synthetic_fixture",
                    "title": "Synthetic evidence",
                    "url": "",
                    "distance": 0.2,
                    "chunk_id": "disease-chunk" if is_disease else "route-chunk",
                    "route": "common",
                }
            ]

        llm = _FakeGemini()
        rag_status = {
            "enabled": True,
            "index_version": "test-v2",
            "collections": ["common", "safety"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            outcome = build_route(
                route="weakness",
                run_dir=run_dir,
                rag_status=rag_status,
                llm=llm,
                retrieve_fn=retrieve,
                max_attempts=1,
            )
            bundle = json.loads((run_dir / "routes" / "weakness.json").read_text())

        self.assertEqual(outcome, "wrote")
        self.assertEqual(llm.calls, 2)
        self.assertTrue(any(query.startswith("Myasthenia gravis ") for query in rag_queries))
        candidate = bundle["disease_candidates"][0]
        self.assertIn(candidate["name"], candidate["retrieval_query"])
        disease_source_ids = {
            source["id"]
            for source in bundle["sources"]
            if candidate["id"] in source["retrieval_scopes"]
        }
        semantic_sources = set(bundle["proposal"]["semantic_options"][0]["source_ids"])
        self.assertTrue(semantic_sources & disease_source_ids)
        self.assertEqual(
            bundle["lifecycle"],
            {"status": "model_generated_provisional", "executable": False},
        )

    def test_validator_rejects_clue_without_disease_name_retrieval_source(self) -> None:
        questionnaire = {
            "questions": [
                {
                    "field": "choice_field",
                    "kind": "choice",
                    "options": ["yes"],
                }
            ]
        }
        candidate = {
            "id": "sample__disease",
            "name": "Example disease",
            "retrieval_query": "Example disease diagnostic features",
            "discovery_source_ids": ["route-source"],
            "disease_rag_source_ids": ["disease-source"],
        }
        proposal = {
            "route": "sample",
            "evidence_status": "limited",
            "route_review": {
                "recommended_disposition": "questionnaire",
                "recommended_clinical_domain": None,
                "rationale": "Synthetic.",
                "source_ids": ["route-source"],
            },
            "fact_proposals": [
                {
                    "code": "sample__fact",
                    "description": "Synthetic fact.",
                    "kind": "finding",
                    "safety_candidate": False,
                    "disease_ids": ["sample__disease"],
                    "source_ids": ["route-source"],
                }
            ],
            "semantic_options": [],
            "profile_status": "proposed",
            "profiles": [],
            "safety_proposals": [],
            "unsupported_requirements": [],
            "review_notes": [],
        }
        with self.assertRaisesRegex(ValueError, "疾病名稱檢索"):
            validate_proposal(
                proposal,
                route="sample",
                questionnaire=questionnaire,
                catalog_entry={"disposition": "questionnaire"},
                existing_fact_codes=set(),
                source_ids={"route-source", "disease-source"},
                source_scopes={
                    "route-source": {"route_discovery"},
                    "disease-source": {"sample__disease"},
                },
                disease_candidates=[candidate],
            )

    def test_candidate_routes_remain_runtime_isolated(self) -> None:
        self.assertEqual(set(DISEASE_ROUTES), {"abdomen", "chest", "headache"})
        self.assertEqual(len(CANDIDATE_DISEASE_ROUTES), 49)
        self.assertNotIn("weakness", DISEASE_ROUTES)

    def test_compiler_repairs_only_single_disease_citations_and_unreachable_facts(self) -> None:
        output = {
            "route_review": {"source_ids": []},
            "fact_proposals": [
                {"code": "sample__disease__reachable", "source_ids": []},
                {"code": "sample__disease__text_only", "source_ids": ["route-source"]},
            ],
            "semantic_options": [
                {
                    "mapping": {"findings": ["sample__disease__reachable"]},
                    "source_ids": [],
                }
            ],
            "profiles": [
                {
                    "must_not_miss": False,
                    "safety_rule_codes": [],
                    "source_ids": [],
                    "clues": [
                        {
                            "fact": "sample__disease__reachable",
                            "status": "present",
                            "source_ids": [],
                        },
                        {
                            "fact": "sample__disease__text_only",
                            "status": "present",
                            "source_ids": [],
                        },
                    ],
                }
            ],
            "profile_status": "proposed",
            "safety_proposals": [],
            "unsupported_requirements": [],
            "review_notes": [],
        }
        candidate = {
            "id": "sample__disease",
            "disease_rag_source_ids": ["disease-source"],
        }
        _normalize_focused_output(
            output,
            candidate=candidate,
            focused_sources=[{"id": "disease-source"}],
            disposition="questionnaire",
        )
        self.assertEqual(output["route_review"]["source_ids"], ["disease-source"])
        self.assertEqual(
            [item["code"] for item in output["fact_proposals"]],
            ["sample__disease__reachable"],
        )
        self.assertEqual(len(output["profiles"][0]["clues"]), 1)
        self.assertTrue(output["unsupported_requirements"])
        self.assertTrue(any("unverified" in note["note"] for note in output["review_notes"]))

    def test_discovery_citation_repair_stays_inside_route_evidence_pack(self) -> None:
        discovery = {
            "diseases": [{"source_ids": []}],
            "review_notes": [{"source_ids": ["unknown"]}],
        }
        _normalize_discovery_citations(
            discovery,
            source_ids={"route-source-a", "route-source-b"},
        )
        expected = ["route-source-a", "route-source-b"]
        self.assertEqual(discovery["diseases"][0]["source_ids"], expected)
        self.assertEqual(discovery["review_notes"][0]["source_ids"], expected)
        self.assertIn("unverified", discovery["review_notes"][-1]["note"])

    def test_code_namespacing_updates_all_internal_references(self) -> None:
        output = {
            "fact_proposals": [{"code": "sample__weakness"}],
            "semantic_options": [{"mapping": {"findings": ["sample__weakness"]}}],
            "safety_proposals": [
                {
                    "code": "experimental_sample__danger",
                    "when": {"any_findings": ["sample__weakness"]},
                }
            ],
            "profiles": [
                {
                    "safety_rule_codes": ["experimental_sample__danger"],
                    "clues": [{"fact": "sample__weakness"}],
                }
            ],
            "review_notes": [],
        }
        candidate = {
            "id": "sample__disease",
            "disease_rag_source_ids": ["disease-source"],
        }
        _namespace_candidate_codes(output, candidate=candidate)
        fact_code = output["fact_proposals"][0]["code"]
        safety_code = output["safety_proposals"][0]["code"]
        self.assertTrue(fact_code.startswith("sample__disease__"))
        self.assertTrue(safety_code.startswith("experimental_sample__disease__"))
        self.assertEqual(output["semantic_options"][0]["mapping"]["findings"], [fact_code])
        self.assertEqual(output["profiles"][0]["clues"][0]["fact"], fact_code)
        self.assertEqual(output["profiles"][0]["safety_rule_codes"], [safety_code])
        self.assertEqual(output["safety_proposals"][0]["when"]["any_findings"], [fact_code])

    def test_route_level_failure_stub_keeps_urgent_without_clinical_rules(self) -> None:
        output = _failed_route_level_output(
            route="stab_wound",
            catalog_entry={"disposition": "urgent", "clinical_domain": None},
            source_ids=["route-source"],
            exc=ValueError("synthetic schema failure"),
        )
        self.assertEqual(output["evidence_status"], "insufficient")
        self.assertEqual(output["route_review"]["recommended_disposition"], "urgent")
        self.assertEqual(output["profile_status"], "not_applicable")
        for key in ("fact_proposals", "semantic_options", "profiles", "safety_proposals"):
            self.assertFalse(output[key])
        self.assertEqual(output["review_notes"][0]["severity"], "critical")


if __name__ == "__main__":
    unittest.main()
