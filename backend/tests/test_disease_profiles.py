import copy
import json
import unittest
from pathlib import Path

from amie.clinical_facts import normalize_fact
from amie.disease_profiles import (
    attach_safety_conditions,
    load_profile_document,
    question_utility,
    score_diseases,
    validate_profile_document,
)
from domain.questionnaires import build_questionnaire


def fact(code, status="present", evidence=None):
    return {
        "code": code,
        "status": status,
        "evidence": evidence or code,
        "source": "test",
        "turn": 1,
    }


class DiseaseProfileValidationTests(unittest.TestCase):
    def test_deployed_profile_is_versioned_and_provisional(self):
        document = load_profile_document()

        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(document["route"], "chest")
        self.assertGreaterEqual(len(document["profiles"]), 10)
        self.assertTrue(
            all(profile["review_status"] == "provisional" for profile in document["profiles"])
        )
        self.assertTrue(
            all(
                clue["weight"] == 1 for profile in document["profiles"] for clue in profile["clues"]
            )
        )

    def test_unknown_fact_duplicate_id_and_missing_source_are_rejected(self):
        document = copy.deepcopy(load_profile_document())
        document["profiles"][0]["clues"][0]["fact"] = "model_invented_fact"
        with self.assertRaisesRegex(ValueError, "白名單"):
            validate_profile_document(document)

        document = copy.deepcopy(load_profile_document())
        document["profiles"][1]["id"] = document["profiles"][0]["id"]
        with self.assertRaisesRegex(ValueError, "重複疾病"):
            validate_profile_document(document)

        document = copy.deepcopy(load_profile_document())
        document["profiles"][0]["clues"][0]["source_ids"] = ["unknown-source"]
        with self.assertRaisesRegex(ValueError, "未知來源"):
            validate_profile_document(document)

    def test_invalid_weight_and_unverified_coding_are_rejected(self):
        document = copy.deepcopy(load_profile_document())
        document["profiles"][0]["clues"][0]["weight"] = 0
        with self.assertRaisesRegex(ValueError, "正整數"):
            validate_profile_document(document)

        document = copy.deepcopy(load_profile_document())
        document["profiles"][0]["coding"] = {
            "system": "http://snomed.info/sct",
            "code": "394659003",
            "display": "Acute coronary syndrome",
            "verified": False,
        }
        with self.assertRaisesRegex(ValueError, "未驗證"):
            validate_profile_document(document)

    def test_wrong_schema_generation_and_review_metadata_are_rejected(self):
        document = copy.deepcopy(load_profile_document())
        document["schema_version"] = 2
        with self.assertRaisesRegex(ValueError, "schema_version"):
            validate_profile_document(document)

        document = copy.deepcopy(load_profile_document())
        del document["generation"]["model"]
        with self.assertRaisesRegex(ValueError, "generation"):
            validate_profile_document(document)

        document = copy.deepcopy(load_profile_document())
        document["profiles"][0]["review_status"] = "reviewed"
        with self.assertRaisesRegex(ValueError, "reviewer"):
            validate_profile_document(document)

    def test_clinical_fact_rejects_unknown_codes_missing_evidence_and_extra_fields(self):
        self.assertIsNone(normalize_fact(fact("model_invented_fact")))
        missing_evidence = fact("chest_pressure")
        missing_evidence["evidence"] = ""
        self.assertIsNone(normalize_fact(missing_evidence))
        with_extra = {**fact("chest_pressure"), "disease": "模型自創疾病"}
        self.assertIsNone(normalize_fact(with_extra))


class DiseaseScoringTests(unittest.TestCase):
    def test_safety_directions_come_from_json_without_fake_votes(self):
        result = attach_safety_conditions(
            "chest",
            [
                {
                    "code": "chest_diaphoresis",
                    "label": "胸部不適合併冒冷汗",
                    "evidence": "冒冷汗",
                    "level": "urgent",
                    "possible_conditions": ["模型自創疾病"],
                }
            ],
            facts=[],
        )

        self.assertEqual(result["status"], "safety_triggered")
        self.assertEqual(result["top"], [])
        self.assertEqual(
            result["safety_triggered_conditions"],
            [
                {
                    "name": "急性冠心症（含心肌梗塞）",
                    "profile_id": "acute_coronary_syndrome",
                    "coding": None,
                    "source": "safety_rule",
                    "triggered_by": [
                        {
                            "rule_code": "chest_diaphoresis",
                            "rule_label": "胸部不適合併冒冷汗",
                            "evidence": "冒冷汗",
                        }
                    ],
                }
            ],
        )
        self.assertNotIn(
            "net_votes",
            result["safety_triggered_conditions"][0],
        )

    def test_non_chest_safety_direction_does_not_invent_profile_id(self):
        result = attach_safety_conditions(
            "headache",
            [
                {
                    "code": "semantic_severe_headache_visual_change",
                    "label": "劇烈頭痛合併視覺異常",
                    "evidence": "頭痛且視力模糊",
                }
            ],
        )

        self.assertEqual(result["method"], "safety_rule_v1")
        self.assertEqual(
            [item["name"] for item in result["safety_triggered_conditions"]],
            ["蜘蛛膜下腔出血", "顱內出血"],
        )
        self.assertTrue(
            all(item["profile_id"] is None for item in result["safety_triggered_conditions"])
        )

    def test_support_opposition_unknown_and_coverage_are_separate(self):
        result = score_diseases(
            [
                fact("chest_pressure", evidence="重物壓迫"),
                fact("diaphoresis", evidence="冒冷汗"),
                fact("reproducible_tenderness", evidence="按壓會痛"),
            ]
        )
        acs = next(item for item in result["ranked"] if item["id"] == "acute_coronary_syndrome")

        self.assertEqual(acs["support_votes"], 2)
        self.assertEqual(acs["oppose_votes"], 1)
        self.assertEqual(acs["net_votes"], 1)
        self.assertEqual(acs["coverage"], 0.5)
        self.assertIn("exertional_trigger", acs["missing_facts"])

    def test_absent_finding_is_evaluated_but_does_not_match_present_rule(self):
        result = score_diseases([fact("reproducible_tenderness", "absent", "沒有壓痛")])
        costochondritis = next(item for item in result["ranked"] if item["id"] == "costochondritis")

        self.assertEqual(costochondritis["support_votes"], 0)
        self.assertGreater(costochondritis["coverage"], 0)
        self.assertEqual(result["status"], "insufficient")

    def test_future_non_unit_weight_changes_only_the_programmed_vote(self):
        document = copy.deepcopy(load_profile_document())
        document["profiles"][0]["clues"][0]["weight"] = 3
        result = score_diseases([fact("chest_pressure")], document=document)

        self.assertEqual(result["top"][0]["id"], "acute_coronary_syndrome")
        self.assertEqual(result["top"][0]["net_votes"], 3)

    def test_same_facts_produce_identical_order_independent_of_input_order(self):
        facts = [fact("palpitations"), fact("syncope"), fact("dizziness_unspecified")]

        first = score_diseases(facts)
        second = score_diseases(list(reversed(facts)))

        self.assertEqual(
            [item["id"] for item in first["ranked"]],
            [item["id"] for item in second["ranked"]],
        )
        self.assertEqual(first["top"], second["top"])

    def test_question_utility_uses_only_frozen_profile_votes(self):
        questionnaire = build_questionnaire("chest")
        assessment = score_diseases([fact("chest_pressure")])
        associated = next(item for item in questionnaire if item["field"] == "associated")
        onset = next(item for item in questionnaire if item["field"] == "onset")

        self.assertGreater(question_utility(associated, assessment), 0)
        self.assertEqual(question_utility(onset, assessment), 0)

    def test_must_not_miss_list_remains_visible_without_supporting_votes(self):
        result = score_diseases([])

        self.assertEqual(result["status"], "insufficient")
        self.assertGreaterEqual(len(result["must_not_miss"]), 4)
        self.assertTrue(all(item["must_not_miss"] for item in result["must_not_miss"]))

    def test_fixed_gold_cases_are_provider_independent(self):
        path = Path(__file__).parent / "data" / "chest_vote_gold_cases.json"
        cases = json.loads(path.read_text(encoding="utf-8"))

        for case in cases:
            facts = [fact(code, evidence=evidence) for code, evidence in case["facts"]]
            provider_rankings = {
                provider: [item["id"] for item in score_diseases(facts)["ranked"]]
                for provider in ("gemini", "groq", "offline-test")
            }
            with self.subTest(case=case["id"]):
                self.assertEqual(
                    provider_rankings["gemini"][0],
                    case["expected_first"],
                )
                self.assertEqual(
                    len({tuple(ranking) for ranking in provider_rankings.values()}),
                    1,
                )


if __name__ == "__main__":
    unittest.main()
