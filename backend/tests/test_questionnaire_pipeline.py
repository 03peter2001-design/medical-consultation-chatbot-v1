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
from app.services import rag as rag_service
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


def _gemini_response(task: str) -> str:
    responses = {
        "chief_complaint": "left-sided chest pain for 30 minutes",
        "present_illness": "Pressure-like chest pain developed during exertion.",
        "past_history": "Not provided",
        "drug_history": ("Past medications: none reported. Current medications: none reported."),
        "drug_allergy_history": "Not provided",
        "personal_history": "The patient has never smoked cigarettes.",
        "family_history": "Not provided",
        "differential_diagnoses": [
            "Acute coronary syndrome",
            "Pericarditis",
            "Gastroesophageal reflux disease",
        ],
        "must_not_miss": [
            "Acute coronary syndrome",
            "Aortic dissection",
            "Pulmonary embolism",
            "Tension pneumothorax",
            "Cardiac tamponade",
        ],
        "physical_examination": ["Bilateral blood pressure measurement"],
        "laboratory": ["High-sensitivity cardiac troponin"],
        "imaging": ["Chest radiograph"],
    }
    return json.dumps({task: responses[task]}, ensure_ascii=False)


def _generate_gemini_section(messages, **_kwargs) -> str:
    payload = json.loads(messages[-1]["content"])
    return _gemini_response(payload["task"])


class QuestionnairePipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.repository = ConsultationRepository(
            Path(self.temp_directory.name) / "questionnaire.db"
        )
        self.sessions: dict[str, dict] = {}
        self.generate_text = Mock(side_effect=_generate_gemini_section)
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

    def test_questionnaire_models_use_dedicated_defaults_and_keep_shared_override(self):
        self.assertEqual(
            runtime.resolve_gemini_summary_model("extraction", {}),
            "gemini-3.5-flash-lite",
        )
        self.assertEqual(
            runtime.resolve_gemini_summary_model("reasoning", {}),
            "gemini-3.6-flash",
        )
        self.assertEqual(
            runtime.resolve_gemini_summary_model(
                "extraction",
                {"GEMINI_MODEL": "gemini-shared"},
            ),
            "gemini-shared",
        )
        self.assertEqual(
            runtime.resolve_gemini_summary_model(
                "extraction",
                {
                    "GEMINI_MODEL": "gemini-shared",
                    "GEMINI_EXTRACTION_MODEL": "gemini-extraction",
                },
            ),
            "gemini-extraction",
        )

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
        with patch.object(
            patient, "retrieve_knowledge_base_block", side_effect=responses
        ) as retrieve:
            contexts, sources = patient._questionnaire_rag_contexts(
                {"type": "chest", "reason": "胸痛", "age": "36"}
            )

        self.assertEqual(
            contexts,
            {"diagnosis": "A context", "laboratory": "B context", "imaging": "C context"},
        )
        self.assertEqual(
            [call.args[0] for call in retrieve.call_args_list],
            ["A", "B", "C"],
        )
        self.assertEqual([source["title"] for source in sources], ["A", "B", "C"])

    def test_knowledge_base_adapter_binds_abc_to_retrieval_purposes(self):
        with (
            patch.object(
                rag_service,
                "retrieve_context_block",
                return_value=("evidence", [{"title": "Synthetic"}]),
            ) as retrieve,
            patch.object(
                rag_service.runtime,
                "RAG_STATUS",
                {"index_version": "v2"},
            ),
        ):
            outputs = [
                rag_service.retrieve_knowledge_base_block(
                    knowledge_base,
                    "query",
                    n_results=3,
                    primary_route="chest",
                    patient_data={},
                )
                for knowledge_base in ("A", "B", "C")
            ]

        self.assertEqual(
            [call.kwargs["purpose"] for call in retrieve.call_args_list],
            ["diagnosis", "lab", "imaging"],
        )
        self.assertTrue(all(call.kwargs["stage_scope"] for call in retrieve.call_args_list))
        self.assertEqual(
            [sources[0]["knowledge_base"] for _, sources in outputs],
            ["A", "B", "C"],
        )

    def test_knowledge_base_adapter_marks_unpartitioned_legacy_compatibility(self):
        with (
            patch.object(
                rag_service.runtime,
                "RAG_STATUS",
                {"index_version": "legacy"},
            ),
            patch.object(
                rag_service,
                "retrieve_context_block",
                return_value=("legacy evidence", [{"title": "Legacy"}]),
            ) as retrieve,
        ):
            context, sources = rag_service.retrieve_knowledge_base_block(
                "A",
                "query",
                n_results=3,
                primary_route="chest",
                patient_data={},
            )

        self.assertEqual(context, "legacy evidence")
        self.assertFalse(retrieve.call_args.kwargs["stage_scope"])
        self.assertEqual(sources[0]["knowledge_base"], "A")
        self.assertEqual(sources[0]["partition_mode"], "legacy_unpartitioned")

    def test_fixed_questions_run_locally_then_each_report_question_gets_its_own_prompt(self):
        session_id = "fixed-order"
        extraction_generate_text = Mock(side_effect=_generate_gemini_section)
        reasoning_generate_text = Mock(side_effect=_generate_gemini_section)
        clients = {
            "extraction": SimpleNamespace(
                model="gemini-extraction-test",
                generate_text=extraction_generate_text,
            ),
            "reasoning": SimpleNamespace(
                model="gemini-reasoning-test",
                generate_text=reasoning_generate_text,
            ),
        }
        with (
            patch.object(patient, "sessions", self.sessions),
            patch.object(patient, "consultation_repository", self.repository),
            patch.object(
                patient,
                "get_gemini_summary_client",
                side_effect=clients.__getitem__,
            ),
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
        self.assertEqual(extraction_generate_text.call_count, 7)
        self.assertEqual(reasoning_generate_text.call_count, 5)
        submitted_by_task = {}
        called_tasks = []
        for call in [
            *extraction_generate_text.call_args_list,
            *reasoning_generate_text.call_args_list,
        ]:
            messages = call.args[0]
            self.assertNotIn("每次請求只回答", messages[0]["content"])
            submitted = json.loads(messages[-1]["content"])
            called_tasks.append(submitted["task"])
            submitted_by_task[submitted["task"]] = submitted
            submitted_fields = [
                item["field"] for item in submitted["patient_context"]["questionnaire_answers"]
            ]
            if submitted["task"] == "chief_complaint":
                self.assertEqual(
                    submitted_fields,
                    [
                        field
                        for field in expected_fields
                        if field not in {"name", "age", "birth_date", "gender", "sex"}
                    ],
                )
            elif submitted["task"] == "drug_history":
                self.assertEqual(submitted_fields, ["past_meds", "current_meds"])
            else:
                self.assertEqual(submitted_fields, expected_fields)
            if submitted["task"] != "drug_history":
                self.assertEqual(
                    submitted["patient_context"]["questionnaire_answers"][0]["answer"],
                    "我胸痛而且昏倒",
                )
        self.assertEqual(
            called_tasks,
            [
                "chief_complaint",
                "present_illness",
                "past_history",
                "drug_history",
                "drug_allergy_history",
                "personal_history",
                "family_history",
                "differential_diagnoses",
                "must_not_miss",
                "physical_examination",
                "laboratory",
                "imaging",
            ],
        )
        for task in called_tasks[:7]:
            self.assertNotIn("retrieved_evidence", submitted_by_task[task])
        self.assertNotIn(
            "patient_demographics",
            submitted_by_task["chief_complaint"]["patient_context"],
        )
        self.assertEqual(
            [
                answer["field"]
                for answer in submitted_by_task["drug_history"]["patient_context"][
                    "questionnaire_answers"
                ]
            ],
            ["past_meds", "current_meds"],
        )
        self.assertEqual(
            submitted_by_task["differential_diagnoses"]["retrieved_evidence"],
            "知識庫A內容",
        )
        self.assertEqual(submitted_by_task["laboratory"]["retrieved_evidence"], "知識庫B內容")
        self.assertEqual(submitted_by_task["imaging"]["retrieved_evidence"], "知識庫C內容")
        expected_focus = [
            "Acute coronary syndrome",
            "Aortic dissection",
            "Pulmonary embolism",
            "Tension pneumothorax",
            "Cardiac tamponade",
        ]
        self.assertEqual(
            submitted_by_task["physical_examination"]["focus_conditions"], expected_focus
        )
        self.assertEqual(submitted_by_task["laboratory"]["focus_conditions"], expected_focus)
        self.assertEqual(submitted_by_task["imaging"]["focus_conditions"], expected_focus)
        self.assertNotIn("_safety", data)
        self.assertNotIn("_amie", data)
        self.assertEqual(data["_interview_pipeline"]["model"], "gemini-reasoning-test")
        self.assertEqual(
            data["_interview_pipeline"]["models"],
            {
                "extraction": "gemini-extraction-test",
                "reasoning": "gemini-reasoning-test",
            },
        )

        record = self.repository.get_by_registration_number(response["queue_number"])
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["triage_level"], "routine")
        self.assertIn("【病歷摘要 EMR】", record["structured_note"])
        self.assertIn("Chief Complaint:", record["structured_note"])
        self.assertIn(
            "A 36-year-old male patient presents with left-sided chest pain for 30 minutes.",
            record["structured_note"],
        )
        self.assertIn("Personal History:", record["structured_note"])
        self.assertIn("Family History:", record["structured_note"])
        self.assertIn("【初步鑑別診斷（前3項最可能）】", record["structured_note"])
        self.assertIn("【防漏診鑑別 — 5個絕對不能漏掉的隱形殺手】", record["structured_note"])
        self.assertIn("【理學檢查】", record["structured_note"])
        self.assertIn("【檢驗（抽血／驗尿）】", record["structured_note"])
        self.assertIn("【影像學決策】", record["structured_note"])
        self.assertNotIn("建議", record["structured_note"])
        self.assertIn("Acute coronary syndrome", record["structured_note"])
        self.assertNotIn("理由：", record["structured_note"])
        self.assertIn("病史擷取：gemini-extraction-test", record["structured_note"])
        self.assertIn("RAG 臨床決策：gemini-reasoning-test", record["structured_note"])
        self.assertIn("Drug History:", record["structured_note"])
        self.assertIn("Past medications: none reported.", record["structured_note"])
        self.assertIn("Current medications: none reported.", record["structured_note"])
        self.assertIn("fixed-questionnaire-complete-drug-history-v9", record["structured_note"])
        self.assertEqual(
            data["_interview_pipeline"]["postprocess"],
            "per_task_gemini_report_after_questionnaire",
        )
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
        self.generate_text.side_effect = lambda *_args, **_kwargs: "not-json"
        with (
            patch.object(patient, "sessions", self.sessions),
            patch.object(patient, "consultation_repository", self.repository),
            patch.object(patient, "get_gemini_summary_client", return_value=self.gemini_client),
            patch.object(patient, "safe_log") as safe_log,
        ):
            with self.assertRaises(HTTPException) as caught:
                self._finish("invalid", "我胸痛")

        self.assertEqual(caught.exception.status_code, 503)
        safe_log.assert_called_once()
        self.assertEqual(safe_log.call_args.kwargs["failure_stage"], "chief_complaint")
        self.assertEqual(self.repository.count(), 0)
        self.assertNotEqual(self.sessions["invalid"]["index"], -1)

    def test_invalid_reasoning_result_fails_closed_after_extraction(self):
        extraction_client = SimpleNamespace(
            model="gemini-extraction-test",
            generate_text=Mock(side_effect=_generate_gemini_section),
        )
        reasoning_client = SimpleNamespace(
            model="gemini-reasoning-test",
            generate_text=Mock(return_value="not-json"),
        )
        clients = {
            "extraction": extraction_client,
            "reasoning": reasoning_client,
        }
        with (
            patch.object(patient, "sessions", self.sessions),
            patch.object(patient, "consultation_repository", self.repository),
            patch.object(
                patient,
                "get_gemini_summary_client",
                side_effect=clients.__getitem__,
            ),
            patch.object(patient, "safe_log") as safe_log,
        ):
            with self.assertRaises(HTTPException) as caught:
                self._finish("invalid-reasoning", "我胸痛")

        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(extraction_client.generate_text.call_count, 7)
        self.assertEqual(reasoning_client.generate_text.call_count, 1)
        safe_log.assert_called_once()
        self.assertEqual(
            safe_log.call_args.kwargs["failure_stage"],
            "differential_diagnoses",
        )
        self.assertEqual(self.repository.count(), 0)
        self.assertNotEqual(self.sessions["invalid-reasoning"]["index"], -1)

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
