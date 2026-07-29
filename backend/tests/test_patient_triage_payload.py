import unittest

from app.routes.patient import (
    _assess_chief_complaint,
    _complaint_routes,
    _copy_prefills_to_secondary_routes,
    _question_payload,
)
from domain.questionnaires import build_questionnaire


class PatientTriagePayloadTests(unittest.TestCase):
    def test_headache_with_right_eye_blurring_stops_at_raw_safety(self):
        data = {}

        route, flags = _assess_chief_complaint(
            "我頭痛，右眼突然看東西很模糊",
            data,
        )

        self.assertEqual(route, "headache")
        self.assertTrue(
            any(flag["code"] == "acute_monocular_visual_change_combination" for flag in flags)
        )
        self.assertNotIn("_chief_assessment", data)

    def test_keeps_all_evidenced_symptom_routes(self):
        data = {
            "_chief_assessment": {
                "route_priority": ["headache", "abdomen"],
            }
        }

        self.assertEqual(
            _complaint_routes(data, "headache"),
            ["headache", "abdomen"],
        )

    def test_copies_imported_history_to_secondary_route_field(self):
        session = {
            "data": {"surgery": "未曾手術"},
            "prefilled_fields": ["surgery"],
        }
        questionnaire = build_questionnaire(["headache", "abdomen"])

        _copy_prefills_to_secondary_routes(session, questionnaire)

        self.assertEqual(session["data"]["abdomen__surgery"], "未曾手術")
        self.assertIn("abdomen__surgery", session["prefilled_fields"])

    def test_urgent_payload_exposes_only_safety_rule_candidates(self):
        session = {
            "session_id": "urgent-payload-test",
            "engine": "amie",
            "index": -1,
            "data": {},
            "triage_level": "urgent",
            "amie_state": {
                "red_flags": [
                    {
                        "code": "chest_diaphoresis",
                        "label": "胸部不適合併冒冷汗",
                        "possible_conditions": [
                            "急性冠心症（含心肌梗塞）",
                        ],
                    },
                    {
                        "code": "chest_syncope",
                        "label": "胸部不適合併昏厥",
                        "possible_conditions": [
                            "急性冠心症（含心肌梗塞）",
                            "致命性心律不整",
                        ],
                    },
                ]
            },
        }

        payload = _question_payload(
            session,
            reply="問診已停止",
            completed=True,
        )

        self.assertEqual(payload["triage"]["level"], "urgent")
        self.assertEqual(
            payload["triage"]["possible_conditions"],
            [
                "急性冠心症（含心肌梗塞）",
                "致命性心律不整",
            ],
        )
        self.assertNotIn("disease_assessment", payload)
        self.assertIn("立即處理", payload["triage"]["message"])

    def test_routine_payload_does_not_expose_condition_candidates(self):
        payload = _question_payload(
            {
                "session_id": "routine-payload-test",
                "index": 0,
                "data": {},
                "triage_level": "routine",
            },
            reply="請描述主訴",
        )

        self.assertNotIn("possible_conditions", payload["triage"])


if __name__ == "__main__":
    unittest.main()
