import unittest
from unittest.mock import patch

from amie.disease_profiles import attach_safety_conditions, score_diseases
from app.models import LoadPatientRequest
from app.routes.doctor import load_patient
from app.routes.patient import _question_payload
from app.services.consultation_reporting import (
    _render_physician_quick_summary,
    _render_structured_note,
    _render_vote_assessment,
    _supported_condition_summaries,
    _validated_workup_items,
    generate_ai_report,
)


def clinical_fact(code: str, evidence: str) -> dict:
    return {
        "code": code,
        "status": "present",
        "evidence": evidence,
        "source": "structured_option",
        "turn": 1,
    }


class _Repository:
    def __init__(self, record: dict):
        self.record = record

    def get(self, queue_number: str) -> dict | None:
        return self.record if queue_number == self.record["queue_number"] else None


class DiseaseApiIsolationTests(unittest.TestCase):
    def test_doctor_load_hydrates_coding_in_stored_assessment(self):
        record = {
            "queue_number": "20000",
            "type": "headache",
            "reason": "頭痛",
            "summary": "摘要",
            "report": "報告",
            "data": {
                "reason": "頭痛",
                "_disease_assessment": {
                    "ranked": [
                        {
                            "id": "meningitis_or_encephalitis",
                            "name": "腦膜炎或腦炎",
                            "coding": None,
                        }
                    ]
                },
            },
            "structured_note": None,
            "structured_sources": [],
            "triage_level": "routine",
            "status": "completed",
        }

        with (
            patch("app.routes.doctor.runtime.consultation_repository", _Repository(record)),
            patch("app.routes.doctor.runtime.doctor_sessions", {}),
            patch("app.routes.doctor.terminology_reference", return_value={}),
        ):
            response = load_patient(
                LoadPatientRequest(queue_number="20000", session_id="doctor-coding")
            )

        self.assertEqual(
            [coding["code"] for coding in response["disease_assessment"]["ranked"][0]["coding"]],
            ["7180009", "45170000"],
        )

    def test_doctor_load_recalculates_headache_and_abdomen_legacy_cases(self):
        records = [
            {
                "queue_number": "20001",
                "type": "headache",
                "reason": "單側跳痛",
                "data": {
                    "reason": "單側跳痛",
                    "location": "單側",
                    "quality": "像脈搏一樣的跳痛",
                },
            },
            {
                "queue_number": "20002",
                "type": "abdomen",
                "reason": "右下腹痛",
                "data": {
                    "reason": "右下腹痛",
                    "location": "右下腹",
                    "quality": "由肚臍周圍痛轉移到右下腹",
                    "associated": "噁心",
                },
            },
        ]
        for record in records:
            record.update(
                {
                    "summary": "摘要",
                    "report": "報告",
                    "structured_note": None,
                    "structured_sources": [],
                    "triage_level": "routine",
                    "status": "completed",
                }
            )
            with (
                self.subTest(route=record["type"]),
                patch(
                    "app.routes.doctor.runtime.consultation_repository",
                    _Repository(record),
                ),
                patch("app.routes.doctor.runtime.doctor_sessions", {}),
                patch(
                    "app.routes.doctor.terminology_reference",
                    return_value={},
                ),
            ):
                response = load_patient(
                    LoadPatientRequest(
                        queue_number=record["queue_number"],
                        session_id=f"doctor-{record['type']}",
                    )
                )

            assessment = response["disease_assessment"]
            self.assertEqual(
                assessment["computed_from"],
                "legacy_recalculation",
            )
            self.assertTrue(assessment["profile_version"].startswith(record["type"]))
            self.assertTrue(assessment["top"])

    def test_doctor_load_rebuilds_safety_directions_for_legacy_urgent_case(self):
        record = {
            "queue_number": "54321",
            "type": "headache",
            "reason": "突然劇烈頭痛",
            "summary": "摘要",
            "report": "報告",
            "data": {
                "reason": "突然劇烈頭痛",
                "_amie": {
                    "red_flags": [
                        {
                            "code": "headache_thunderclap",
                            "label": "突發爆炸性頭痛",
                            "evidence": "突然劇烈頭痛",
                            "level": "urgent",
                        }
                    ]
                },
            },
            "structured_note": None,
            "structured_sources": [],
            "triage_level": "urgent",
            "status": "completed",
        }

        with (
            patch("app.routes.doctor.runtime.consultation_repository", _Repository(record)),
            patch("app.routes.doctor.runtime.doctor_sessions", {}),
            patch("app.routes.doctor.terminology_reference", return_value={}),
        ):
            response = load_patient(
                LoadPatientRequest(queue_number="54321", session_id="doctor-urgent")
            )

        assessment = response["disease_assessment"]
        self.assertEqual(assessment["status"], "safety_triggered")
        self.assertEqual(assessment["computed_from"], "legacy_recalculation")
        self.assertEqual(
            [item["name"] for item in assessment["safety_triggered_conditions"]],
            ["蜘蛛膜下腔出血", "顱內出血"],
        )

    def test_doctor_load_recalculates_legacy_case_and_preserves_old_llm_audit(self):
        record = {
            "queue_number": "12345",
            "type": "chest",
            "reason": "活動時胸口壓迫",
            "summary": "摘要",
            "report": "報告",
            "data": {
                "reason": "活動時胸口壓迫",
                "quality": "壓迫感",
                "_amie": {
                    "differential_hypotheses": [
                        {
                            "condition": "舊模型疾病",
                            "supporting_evidence": ["舊模型輸出"],
                            "opposing_evidence": [],
                        }
                    ]
                },
            },
            "structured_note": None,
            "structured_sources": [],
            "triage_level": "routine",
            "status": "completed",
        }

        with (
            patch("app.routes.doctor.runtime.consultation_repository", _Repository(record)),
            patch("app.routes.doctor.runtime.doctor_sessions", {}),
            patch("app.routes.doctor.terminology_reference", return_value={}),
        ):
            response = load_patient(
                LoadPatientRequest(queue_number="12345", session_id="doctor-test")
            )

        self.assertEqual(
            response["disease_assessment"]["computed_from"],
            "legacy_recalculation",
        )
        self.assertEqual(response["amie_state"]["differential_hypotheses"], [])
        self.assertEqual(
            response["legacy_differential_hypotheses"][0]["condition"],
            "舊模型疾病",
        )

    def test_patient_debug_payload_strips_disease_scores_and_rankings(self):
        session = {
            "session_id": "patient-debug",
            "engine": "amie",
            "index": -1,
            "data": {},
            "triage_level": "routine",
            "transcript": [
                {
                    "turn": 1,
                    "question": {"field": "quality", "prompt": "性質？"},
                    "answer": "壓迫",
                    "decision": {
                        "action": "ask",
                        "disease_votes": [{"id": "secret", "net_votes": 3}],
                    },
                    "result": {
                        "disease_assessment": {"ranked": [{"id": "secret", "name": "不應洩漏"}]},
                        "clinical_facts": [clinical_fact("chest_pressure", "壓迫")],
                    },
                }
            ],
        }

        with patch("app.routes.patient.AMIE_DEBUG_TRACE", True):
            payload = _question_payload(session, reply="下一題", completed=True)

        self.assertNotIn("possible_conditions", payload["triage"])
        self.assertNotIn("disease_votes", payload["amie_debug"]["decision"])
        self.assertNotIn("disease_assessment", payload["amie_debug"]["result"])


class DiseaseReportRestrictionTests(unittest.TestCase):
    def setUp(self):
        self.assessment = score_diseases(
            [
                clinical_fact("chest_pressure", "胸口像被壓住"),
                clinical_fact("exertional_trigger", "走路時發作"),
            ]
        )

    def test_unknown_or_malformed_condition_references_are_discarded(self):
        allowed = {item["id"] for item in self.assessment["ranked"]}
        payload = {
            "laboratory": [
                {
                    "item": "心電圖",
                    "rationale": "評估對應疾病的危險徵象",
                    "linked_condition_ids": ["acute_coronary_syndrome"],
                },
                {
                    "item": "未知檢查",
                    "rationale": "引用模型自行生成的疾病",
                    "linked_condition_ids": ["hallucinated_disease"],
                },
                {
                    "item": "格式錯誤",
                    "rationale": "多出欄位",
                    "linked_condition_ids": ["acute_coronary_syndrome"],
                    "score": 0.9,
                },
            ]
        }

        items = _validated_workup_items(payload, "laboratory", allowed)

        self.assertEqual([item["item"] for item in items], ["心電圖"])

    def test_disease_sections_are_rendered_only_from_the_fixed_assessment(self):
        note = _render_structured_note(
            {"data": {"reason": "活動時胸悶"}},
            self.assessment,
            {
                "emr_summary": "活動時胸悶",
                "physical_exam": [
                    {
                        "item": "生命徵象",
                        "rationale": "評估循環狀態",
                        "linked_condition_ids": ["acute_coronary_syndrome"],
                    },
                    {
                        "item": "模型自創檢查",
                        "rationale": "模型自創疾病",
                        "linked_condition_ids": ["invented"],
                    },
                ],
            },
        )

        self.assertIn(self.assessment["top"][0]["name"], note)
        self.assertIn("生命徵象", note)
        self.assertNotIn("模型自創檢查", note)
        self.assertNotIn("invented", note)
        self.assertIn("不是患病機率", note)

    def test_hallucinated_disease_in_history_summary_is_replaced(self):
        note = _render_structured_note(
            {"data": {"reason": "活動時胸悶"}},
            self.assessment,
            {
                "emr_summary": "病人疑似罹患肺癌。",
                "physical_exam": [],
                "laboratory": [],
                "imaging": [],
            },
        )

        self.assertNotIn("肺癌", note)
        self.assertIn("活動時胸悶", note)

    def test_vote_report_calls_zero_support_data_insufficient(self):
        assessment = score_diseases([])

        rendered = _render_vote_assessment(assessment)

        self.assertIn("沒有取得足夠的支持線索", rendered)
        self.assertNotIn("機率", rendered)

    def test_report_renders_safety_directions_instead_of_insufficient(self):
        assessment = attach_safety_conditions(
            "chest",
            [
                {
                    "code": "chest_diaphoresis",
                    "label": "胸部不適合併冒冷汗",
                    "evidence": "冒冷汗",
                }
            ],
        )

        rendered = _render_vote_assessment(assessment)

        self.assertIn("Safety 規則觸發的鑑別方向", rendered)
        self.assertIn("急性冠心症", rendered)
        self.assertIn("冒冷汗", rendered)
        self.assertNotIn("沒有取得足夠的支持線索", rendered)

    def test_quick_summary_uses_only_supported_fixed_table_conditions(self):
        conditions = _supported_condition_summaries(self.assessment)

        self.assertTrue(conditions)
        self.assertLessEqual(len(conditions), 3)
        self.assertTrue(all(evidence for _, evidence in conditions))
        self.assertNotIn(
            "肋軟骨炎或胸壁疼痛",
            [name for name, _ in conditions],
        )

    def test_quick_summary_is_one_paragraph_with_conditions_and_reasons(self):
        summary = _render_physician_quick_summary(
            {"data": {"reason": "走路時胸口像被壓住"}},
            "病人走路時出現胸口壓迫感。\n無其他已知資料。",
            self.assessment,
        )

        self.assertNotIn("\n", summary)
        self.assertIn("可能疾病包括", summary)
        self.assertIn("急性冠心症", summary)
        self.assertIn("依據：", summary)
        self.assertIn("並非正式診斷", summary)

    def test_quick_summary_states_when_supporting_evidence_is_insufficient(self):
        summary = _render_physician_quick_summary(
            {"data": {"reason": "胸部不適"}},
            "病人主訴胸部不適。",
            score_diseases([]),
        )

        self.assertIn("資料不足", summary)
        self.assertNotIn("可能疾病包括", summary)

    def test_quick_summary_bounds_overlong_model_prose_and_evidence(self):
        assessment = score_diseases([clinical_fact("chest_pressure", "非常長的病人原始描述" * 20)])
        summary = _render_physician_quick_summary(
            {"data": {"reason": "胸口壓迫"}},
            "病史內容" * 100,
            assessment,
        )

        self.assertLessEqual(len(summary), 420)
        self.assertIn("…", summary)

    def test_generated_report_combines_gemini_history_with_fixed_assessment(self):
        record = {
            "type": "chest",
            "triage_level": "routine",
            "data": {
                "type": "chest",
                "gender": "男",
                "age": "58",
                "reason": "走路時胸口壓迫",
                "_disease_assessment": self.assessment,
            },
        }
        with patch(
            "app.services.consultation_reporting.runtime.llm_client.generate_text",
            return_value="58歲男性，走路時出現胸口壓迫感。",
        ) as generate_text:
            report = generate_ai_report(record)

        self.assertIsNotNone(report)
        self.assertNotIn("\n", report)
        self.assertIn("58歲男性", report)
        self.assertIn("可能疾病包括急性冠心症", report)
        self.assertIn("胸口像被壓住", report)
        self.assertNotIn("淨票", report)
        self.assertEqual(generate_text.call_args.kwargs["max_tokens"], 500)


if __name__ == "__main__":
    unittest.main()
