import unittest
from unittest.mock import Mock, patch

from amie.engine import AMIEEngine
from amie.models import ChiefComplaintAssessment
from app.routes.patient import (
    _apply_chief_questionnaire_prefills,
    _assess_chief_complaint,
    _complaint_routes,
    _copy_prefills_to_secondary_routes,
    _question_payload,
)
from app.services.patient_interview import _keyword_matches, local_complaint_route
from domain.questionnaires import build_questionnaire, questionnaire_disposition


class PatientTriagePayloadTests(unittest.TestCase):
    def test_only_approved_routes_are_deterministically_recognized(self):
        self.assertEqual(local_complaint_route("我今天開始胸痛"), "chest")
        self.assertEqual(local_complaint_route("我肚子痛"), "abdomen")
        self.assertIsNone(local_complaint_route("我今天開始發燒"))
        self.assertIsNone(local_complaint_route("突然半身無力，可能中風"))
        self.assertIsNone(local_complaint_route("我沒有胸痛，也沒有呼吸困難"))

    def test_ascii_keywords_require_word_or_phrase_boundaries(self):
        self.assertFalse(_keyword_matches("patient has a cough", "ENT"))
        self.assertFalse(_keyword_matches("current chest discomfort", "ENT"))
        self.assertTrue(_keyword_matches("please assess ENT symptoms", "ENT"))

    def test_candidate_route_dispositions_are_not_available_to_patient_runtime(self):
        self.assertEqual(questionnaire_disposition("chest"), "questionnaire")
        with self.assertRaisesRegex(ValueError, "不支援"):
            questionnaire_disposition("stroke")
        with self.assertRaisesRegex(ValueError, "不支援"):
            build_questionnaire("fever")

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
            "type": "headache",
            "types": ["headache"],
            "_chief_assessment": {
                "route_priority": ["headache", "abdomen"],
            },
        }

        self.assertEqual(
            _complaint_routes(data, "headache"),
            ["headache", "abdomen"],
        )

    def test_provisional_dizziness_route_cannot_be_selected_by_semantic_extraction(self):
        assessment = ChiefComplaintAssessment.model_validate(
            {
                "primary_symptom": "unknown",
                "primary_evidence": "",
                "findings": [
                    {
                        "code": "recent_head_trauma",
                        "status": "present",
                        "evidence": "撞到頭",
                    },
                    {
                        "code": "dizziness_unspecified",
                        "status": "present",
                        "evidence": "頭暈",
                    },
                ],
            }
        )
        extractor = Mock()
        extractor.extract.return_value = (assessment, "")

        with (
            patch("app.routes.patient._get_chief_extractor", return_value=extractor),
            patch(
                "app.routes.patient.classify_complaint",
                side_effect=AssertionError("不得用第二次分類覆蓋語意抽取結果"),
            ),
        ):
            route, flags = _assess_chief_complaint(
                "我早上撞到頭，從一小時之前就開始頭暈",
                {},
            )

        self.assertEqual(route, "other")
        self.assertEqual(flags, [])

    def test_explicit_chief_onset_time_prefills_and_skips_onset_question(self):
        data = {
            "_chief_assessment": {
                "extraction": {
                    "primary_symptom": "headache",
                    "primary_evidence": "頭痛",
                    "onset_time": {
                        "value": "一小時之前",
                        "evidence": "一小時之前",
                    },
                }
            }
        }
        questionnaire = build_questionnaire("headache")

        _apply_chief_questionnaire_prefills(data, questionnaire)

        self.assertEqual(data["onset"], "一小時之前")
        self.assertNotIn(
            "onset",
            AMIEEngine._required_missing(data, questionnaire),
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
