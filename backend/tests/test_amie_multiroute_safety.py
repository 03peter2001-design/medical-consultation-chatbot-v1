"""Regression tests for route-scoped facts and multi-route completion safety."""

import unittest

from amie.clinical_facts import FACT_CODES, facts_for_route
from amie.engine import AMIEEngine
from amie.models import ChiefComplaintAssessment
from amie.safety import detect_structured_red_flags
from domain.questionnaires import build_questionnaire


class NoModelLLM:
    def generate_text(self, messages, **kwargs):
        raise AssertionError("核准選項不應呼叫模型")


def fact(code: str, *, route: str, status: str = "absent") -> dict:
    return {
        "code": code,
        "status": status,
        "evidence": "測試證據",
        "source": "test",
        "turn": 1,
        "route": route,
    }


class MultiRouteFactTests(unittest.TestCase):
    def test_live_scoped_fact_is_not_rebuilt_as_an_unscoped_legacy_fact(self):
        questionnaire = build_questionnaire(["chest", "abdomen"])
        result = AMIEEngine(NoModelLLM()).run_turn(
            route="abdomen",
            answer="輕微，仍可正常活動",
            current_field="abdomen__severity",
            data={
                "type": "chest",
                "types": ["chest", "abdomen"],
                "reason": "胸痛又肚子痛",
                "abdomen__severity": "輕微，仍可正常活動",
            },
            questionnaire=questionnaire,
            prefilled_fields={"name", "gender", "birth_date", "blood_type"},
            turn_count=3,
        )

        severity_facts = [item for item in result.clinical_facts if item["code"] == "severity_mild"]
        self.assertEqual(len(severity_facts), 1)
        self.assertEqual(severity_facts[0]["route"], "abdomen")
        self.assertNotIn("severity_mild", facts_for_route(result.clinical_facts, "chest"))

    def test_secondary_disease_route_with_an_askable_clue_cannot_complete(self):
        engine = AMIEEngine.__new__(AMIEEngine)
        engine.max_turns = None
        questionnaire = build_questionnaire(["chest", "abdomen"])
        data = {
            "type": "chest",
            "types": ["chest", "abdomen"],
            "reason": "胸痛又肚子痛",
            "gender": "男性",
        }
        for question in questionnaire:
            if question["field"] != "abdomen__quality":
                data[question["field"]] = "已填"
        clinical_facts = [fact(code, route="chest") for code in FACT_CODES]
        state = {
            "route": "abdomen",
            "answer": "已填",
            "current_field": "abdomen__associated",
            "data": data,
            "questionnaire": questionnaire,
            "clinical_facts": clinical_facts,
            "turn_count": 10,
            "prefilled_fields": [],
        }

        result = engine._plan_node(state)

        self.assertEqual(result["decision"]["action"], "ask")
        self.assertEqual(result["decision"]["next_field"], "abdomen__quality")
        self.assertIn("abdomen", result["data"]["_disease_assessments_by_route"])
        abdomen_ids = {
            item["id"]
            for item in result["data"]["_disease_assessments_by_route"]["abdomen"]["ranked"]
        }
        self.assertIn("appendicitis", abdomen_ids)
        self.assertFalse(result["decision"]["route_completion"]["abdomen"]["ready"])


class ContradictionSafetyTests(unittest.TestCase):
    def test_new_negation_replaces_stale_positive_before_structured_safety(self):
        previous = ChiefComplaintAssessment.model_validate(
            {
                "primary_symptom": "headache",
                "primary_evidence": "頭痛",
                "severity": {"value": "severe", "evidence": "非常嚴重"},
                "findings": [
                    {
                        "code": "visual_change_unspecified",
                        "status": "present",
                        "evidence": "視力模糊",
                    }
                ],
            }
        )
        correction = ChiefComplaintAssessment.model_validate(
            {
                "primary_symptom": "headache",
                "negated_findings": [
                    {
                        "code": "visual_change_unspecified",
                        "status": "absent",
                        "evidence": "現在沒有視力模糊",
                    }
                ],
            }
        )

        merged = AMIEEngine._merge_safety_assessment(
            {"_semantic_safety_state": previous.as_dict()},
            "headache",
            correction,
        )
        flags = detect_structured_red_flags(merged, {}, "headache")

        self.assertFalse(merged.findings)
        self.assertEqual(
            [(item.code, item.status) for item in merged.negated_findings],
            [("visual_change_unspecified", "absent")],
        )
        self.assertNotIn(
            "semantic_severe_headache_visual_change",
            {flag["code"] for flag in flags},
        )


if __name__ == "__main__":
    unittest.main()
