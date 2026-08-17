import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks, HTTPException

from app import runtime
from app.models import ChatRequest
from app.routes import patient
from app.services import consultation_reporting
from domain.questionnaires import (
    BASIC_QUESTIONNAIRE,
    CHIEF_QUESTIONNAIRE,
    HISTORY_QUESTIONNAIRE,
    build_questionnaire,
    condition_matches,
)
from infrastructure.consultation_repository import ConsultationRepository


def _answer_for(question: dict) -> str:
    kind = question["kind"]
    options = question.get("options", [])
    if kind == "date":
        return "1990-01-01"
    if kind == "duration":
        return question["quick_options"][0]
    if kind == "choice":
        for preferred in ("以上皆無", "未曾手術", "沒有，從未抽菸", "沒有"):
            if preferred in options:
                return preferred
        return options[0]
    if question["field"] == "name":
        return "測試病人"
    return "病人提供的回答"


def _gemini_response() -> str:
    return json.dumps(
        {
            "emr": {
                "cc": "左側胸痛，已持續30分鐘。",
                "pi": "A 36-year-old female presented with pressure-like chest pain.",
                "ph": "未提供",
                "meds": "未提供",
                "allergy": "未提供",
            },
            "differential_diagnoses": [
                {"name": "疾病甲", "rationale": "問卷線索與知識庫A相符。"},
                {"name": "疾病乙", "rationale": "需與主要症狀鑑別。"},
                {"name": "疾病丙", "rationale": "仍有部分相符表現。"},
            ],
            "must_not_miss": [{"name": "嚴重疾病甲", "rationale": "延誤可能造成嚴重後果。"}],
            "physical_examination": [
                {"item": "生命徵象", "rationale": "建議立即確認血行動力學狀態。"}
            ],
            "laboratory": [{"item": "檢驗甲", "rationale": "依知識庫B評估相關指標。"}],
            "imaging": [{"item": "胸部X光", "rationale": "依知識庫C評估胸腔結構。"}],
        },
        ensure_ascii=False,
    )


class QuestionnairePipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.repository = ConsultationRepository(
            Path(self.temp_directory.name) / "questionnaire.db"
        )
        self.sessions: dict[str, dict] = {}
        self.generate_text = Mock(return_value=_gemini_response())
        self.gemini_client = SimpleNamespace(
            model="gemini-test-model",
            generate_text=self.generate_text,
        )

    def tearDown(self):
        self.temp_directory.cleanup()

    def _chat(
        self,
        session_id: str,
        message: str = "",
        *,
        language: str | None = None,
    ) -> dict:
        with (
            patch.object(patient, "INTERVIEW_ENGINE", "questionnaire"),
            patch.object(patient, "current_patient_session", return_value=None),
            patch.object(
                patient,
                "_questionnaire_rag_contexts",
                return_value=(
                    {
                        "diagnosis": "知識庫A內容",
                        "laboratory": "知識庫B內容",
                        "imaging": "知識庫C內容",
                    },
                    [
                        {
                            "title": "合成測試文獻",
                            "source": "synthetic",
                            "url": "",
                            "route": "chest",
                        }
                    ],
                ),
            ),
        ):
            return asyncio.run(
                patient._chat_impl(
                    ChatRequest(session_id=session_id, message=message, language=language),
                    BackgroundTasks(),
                )
            )

    def _finish(self, session_id: str, reason: str) -> tuple[dict, list[str]]:
        response = self._chat(session_id)
        asked_fields: list[str] = []
        while not response["completed"]:
            question = response["question_input"]
            asked_fields.append(question["field"])
            answer = reason if question["field"] == "reason" else _answer_for(question)
            response = self._chat(session_id, answer)
            self.assertLess(len(asked_fields), 100)
        return response, asked_fields

    def test_runtime_defaults_to_questionnaire_and_keeps_aliases(self):
        self.assertEqual(runtime._normalize_interview_engine("questionnaire"), "questionnaire")
        self.assertEqual(runtime._normalize_interview_engine("legacy"), "questionnaire")
        self.assertEqual(runtime._normalize_interview_engine("simple"), "questionnaire")
        self.assertEqual(runtime._normalize_interview_engine("amie"), "amie")
        with self.assertRaises(RuntimeError):
            runtime._normalize_interview_engine("unknown")

    def test_taigi_language_is_snapshotted_and_cannot_change_mid_interview(self):
        with (
            patch.object(patient, "sessions", self.sessions),
            patch.object(patient, "validate_taigi_questionnaires"),
            patch.object(patient, "taigi_questionnaire_provenance", return_value={}),
            patch.object(patient, "localize_question", side_effect=lambda item, _: item),
        ):
            response = self._chat("taigi-session", language="minnan")
            index = self.sessions["taigi-session"]["index"]
            with self.assertRaises(HTTPException) as caught:
                self._chat("taigi-session", language="mandarin")

        self.assertEqual(response["language"], "minnan")
        self.assertEqual(self.sessions["taigi-session"]["language"], "minnan")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.sessions["taigi-session"]["index"], index)

    def test_missing_taigi_assets_fail_before_session_creation(self):
        with (
            patch.object(patient, "sessions", self.sessions),
            patch.object(
                patient,
                "validate_taigi_questionnaires",
                side_effect=patient.TaigiQuestionnaireUnavailable("尚未產生台語問卷"),
            ),
        ):
            with self.assertRaises(HTTPException) as caught:
                self._chat("missing-taigi", language="minnan")

        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("missing-taigi", self.sessions)

    def test_final_report_retrieves_diagnosis_lab_and_imaging_evidence(self):
        responses = [
            ("A context", [{"title": "A", "source": "s", "url": "", "route": "chest"}]),
            ("B context", [{"title": "B", "source": "s", "url": "", "route": "chest"}]),
            ("C context", [{"title": "C", "source": "s", "url": "", "route": "chest"}]),
        ]
        with patch.object(patient, "retrieve_context_block", side_effect=responses) as retrieve:
            contexts, sources = patient._questionnaire_rag_contexts(
                {"type": "chest", "reason": "胸痛", "age": "36"}
            )

        self.assertEqual(
            contexts,
            {"diagnosis": "A context", "laboratory": "B context", "imaging": "C context"},
        )
        self.assertEqual(
            [call.kwargs["purpose"] for call in retrieve.call_args_list],
            [
                "diagnosis",
                "lab",
                "imaging",
            ],
        )
        self.assertEqual([source["title"] for source in sources], ["A", "B", "C"])

    def test_fixed_questions_run_locally_then_one_complete_payload_goes_to_gemini(self):
        session_id = "fixed-order"
        with (
            patch.object(patient, "sessions", self.sessions),
            patch.object(patient, "consultation_repository", self.repository),
            patch.object(patient, "get_gemini_summary_client", return_value=self.gemini_client),
            patch.object(
                patient,
                "detect_red_flags",
                side_effect=AssertionError("safety rules must not run"),
            ),
            patch.object(
                patient,
                "_assess_chief_complaint",
                side_effect=AssertionError("semantic extraction must not run"),
            ),
            patch.object(
                patient,
                "_get_amie_engine",
                side_effect=AssertionError("AMIE must not run"),
            ),
            patch.object(
                patient,
                "process_background_summaries",
                side_effect=AssertionError("background reporting must not run"),
            ),
        ):
            response, asked_fields = self._finish(session_id, "我胸痛而且昏倒")

        data = self.sessions[session_id]["data"]
        expected_fields = [
            item["field"] for item in build_questionnaire("chest") if condition_matches(item, data)
        ]
        self.assertEqual(asked_fields, expected_fields)
        self.assertEqual(self.generate_text.call_count, 1)
        messages = self.generate_text.call_args.args[0]
        self.assertIn("資深急診醫師", messages[0]["content"])
        self.assertIn("不做正式診斷", messages[0]["content"])
        submitted = json.loads(messages[-1]["content"])
        self.assertEqual(
            [item["field"] for item in submitted["questionnaire_answers"]],
            expected_fields,
        )
        self.assertEqual(
            submitted["questionnaire_answers"][0]["answer"],
            "我胸痛而且昏倒",
        )
        self.assertEqual(
            submitted["medical_knowledge"],
            {
                "A_differential_and_danger_signs": "知識庫A內容",
                "B_laboratory": "知識庫B內容",
                "C_imaging": "知識庫C內容",
            },
        )
        self.assertNotIn("_safety", data)
        self.assertNotIn("_amie", data)
        self.assertEqual(data["_interview_pipeline"]["model"], "gemini-test-model")

        record = self.repository.get_by_registration_number(response["queue_number"])
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["triage_level"], "routine")
        self.assertIn("【病歷摘要 EMR】", record["structured_note"])
        self.assertIn("CC（主訴）：", record["structured_note"])
        self.assertIn("【初步鑑別診斷（前3項最可能）】", record["structured_note"])
        self.assertIn("【防漏診鑑別 — 5個絕對不能漏掉的隱形殺手】", record["structured_note"])
        self.assertIn("【理學檢查】", record["structured_note"])
        self.assertIn("【檢驗（抽血／驗尿）】", record["structured_note"])
        self.assertIn("【影像學決策】", record["structured_note"])
        self.assertNotIn("建議", record["structured_note"])
        self.assertIn("fixed-questionnaire-six-part-rag-v3", record["structured_note"])
        self.assertEqual(record["structured_sources"][0]["title"], "合成測試文獻")

    def test_unknown_complaint_uses_common_fixed_questions_instead_of_handoff(self):
        with (
            patch.object(patient, "sessions", self.sessions),
            patch.object(patient, "consultation_repository", self.repository),
            patch.object(patient, "get_gemini_summary_client", return_value=self.gemini_client),
        ):
            response, asked_fields = self._finish("common", "我有一個無法分類的不舒服")

        data = self.sessions["common"]["data"]
        common = [*CHIEF_QUESTIONNAIRE, *BASIC_QUESTIONNAIRE, *HISTORY_QUESTIONNAIRE]
        expected = [item["field"] for item in common if condition_matches(item, data)]
        self.assertEqual(asked_fields, expected)
        self.assertTrue(response["completed"])
        record = self.repository.get_by_registration_number(response["queue_number"])
        self.assertEqual(record["type"], "other")
        self.assertEqual(record["status"], "completed")

    def test_invalid_gemini_result_fails_explicitly_and_does_not_create_record(self):
        self.generate_text.return_value = "not-json"
        with (
            patch.object(patient, "sessions", self.sessions),
            patch.object(patient, "consultation_repository", self.repository),
            patch.object(patient, "get_gemini_summary_client", return_value=self.gemini_client),
        ):
            with self.assertRaises(HTTPException) as caught:
                self._finish("invalid", "我胸痛")

        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(self.repository.count(), 0)
        self.assertNotEqual(self.sessions["invalid"]["index"], -1)

    def test_reporting_helpers_never_rebuild_questionnaire_disease_votes(self):
        record = {
            "type": "chest",
            "reason": "胸痛",
            "data": {
                "type": "chest",
                "types": ["chest"],
                "reason": "胸痛",
                "_interview_pipeline": {"engine": "questionnaire", "version": 2},
            },
        }
        with patch.object(
            consultation_reporting,
            "score_diseases",
            side_effect=AssertionError("questionnaire records must not be scored"),
        ):
            self.assertEqual(consultation_reporting._assessment_for_record(record), {})


if __name__ == "__main__":
    unittest.main()
