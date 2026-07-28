import os
import tempfile
import unittest
from pathlib import Path

from infrastructure.consultation_repository import ConsultationRepository


class ConsultationRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "consultations.db"
        self.repository = ConsultationRepository(self.database_path)

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_create_and_get_preserves_complete_result(self):
        record = {
            "session_id": "patient-session-1",
            "type": "chest",
            "reason": "胸口悶",
            "summary": "患者基本資料",
            "report": "AI 初步評估",
            "data": {
                "name": "測試病人",
                "pain_locations": [{"id": "front_chest_center"}],
                "_amie": {"red_flags": [{"code": "chest_syncope"}]},
                "_amie_trace": [
                    {
                        "turn": 1,
                        "answer": "胸口悶",
                        "decision": {
                            "action": "complete",
                            "source": "safety_rule",
                        },
                        "reason": "Safety 層命中警訊。",
                    }
                ],
            },
            "triage_level": "urgent",
            "status": "completed",
        }

        queue_number = self.repository.create(record)
        # A new repository instance represents reading after an app restart.
        reopened_repository = ConsultationRepository(self.database_path)
        saved = reopened_repository.get(queue_number)

        self.assertRegex(queue_number, r"^\d{3}$")
        self.assertNotEqual(queue_number, "000")
        self.assertEqual(saved["session_id"], "patient-session-1")
        self.assertEqual(saved["type"], "chest")
        self.assertEqual(saved["reason"], "胸口悶")
        self.assertEqual(saved["report"], "AI 初步評估")
        self.assertEqual(saved["triage_level"], "urgent")
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["data"], record["data"])
        self.assertEqual(
            saved["data"]["_amie_trace"][0]["reason"],
            "Safety 層命中警訊。",
        )
        self.assertTrue(saved["created_at"].endswith("+00:00"))

    def test_routine_result_uses_five_digit_display_number(self):
        queue_number = self.repository.create(
            {
                "type": "headache",
                "summary": "摘要",
                "report": "報告",
                "data": {},
                "triage_level": "routine",
            }
        )

        self.assertRegex(queue_number, r"^\d{5}$")
        self.assertEqual(
            self.repository.get(queue_number)["queue_number"],
            queue_number,
        )

    def test_fixed_synthetic_record_is_idempotently_updated(self):
        self.repository.upsert_fixed(
            "00000",
            {
                "type": "chest",
                "summary": "舊摘要",
                "report": "舊報告",
                "data": {},
            },
        )
        self.repository.upsert_fixed(
            "00000",
            {
                "type": "headache",
                "summary": "新摘要",
                "report": "新報告",
                "data": {"reason": "頭痛"},
                "status": "synthetic_test",
            },
        )

        saved = self.repository.get("00000")
        self.assertEqual(self.repository.count(), 1)
        self.assertEqual(saved["type"], "headache")
        self.assertEqual(saved["summary"], "新摘要")
        self.assertEqual(saved["data"], {"reason": "頭痛"})

    def test_database_file_is_owner_only(self):
        if os.name == "nt":
            self.skipTest("POSIX file permissions are not available")
        mode = self.database_path.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_missing_queue_number_returns_none(self):
        self.assertIsNone(self.repository.get("12345"))

    def test_list_summaries_supports_search_and_pagination(self):
        first_queue = self.repository.create(
            {
                "type": "chest",
                "reason": "活動時胸悶",
                "summary": "摘要一",
                "report": "不應出現在清單",
                "data": {
                    "name": "王小明",
                    "gender": "男",
                    "age": "52",
                },
                "triage_level": "urgent",
            }
        )
        self.repository.create(
            {
                "type": "headache",
                "reason": "頭痛",
                "summary": "摘要二",
                "report": "不應出現在清單",
                "data": {"name": "陳美玲", "gender": "女", "age": "38"},
            }
        )

        result = self.repository.list_summaries(
            search="王小明",
            limit=1,
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(
            result["items"][0]["queue_number"],
            first_queue,
        )
        self.assertEqual(result["items"][0]["patient_name"], "王小明")
        self.assertEqual(result["items"][0]["age"], "52")
        self.assertEqual(result["items"][0]["triage_level"], "urgent")
        self.assertNotIn("report", result["items"][0])
        self.assertNotIn("data", result["items"][0])

        page = self.repository.list_summaries(limit=1, offset=1)
        self.assertEqual(page["total"], 2)
        self.assertEqual(len(page["items"]), 1)

    def test_structured_note_is_persisted_and_list_marks_it_cached(self):
        queue_number = self.repository.create(
            {
                "type": "abdomen",
                "summary": "腹痛摘要",
                "report": "初步報告",
                "data": {"name": "林先生"},
            }
        )

        saved = self.repository.save_structured_note(
            queue_number,
            "六段式 AI 總結",
            [{"title": "Abdominal Pain", "url": "https://example.test"}],
        )
        reopened = ConsultationRepository(self.database_path)
        record = reopened.get(queue_number)
        summary = reopened.list_summaries(search=queue_number)["items"][0]

        self.assertTrue(saved)
        self.assertEqual(record["structured_note"], "六段式 AI 總結")
        self.assertEqual(
            record["structured_sources"][0]["title"],
            "Abdominal Pain",
        )
        self.assertTrue(record["structured_note_created_at"])
        self.assertTrue(summary["has_structured_note"])

    def test_async_summary_status_and_report_can_be_updated(self):
        queue_number = self.repository.create(
            {
                "type": "headache",
                "summary": "患者資料已保存",
                "report": "摘要產生中",
                "data": {"name": "陳小姐"},
                "status": "summary_pending",
            }
        )

        self.assertEqual(
            self.repository.get(queue_number)["status"],
            "summary_pending",
        )
        self.assertTrue(
            self.repository.save_generated_report(
                queue_number,
                "背景產生的 AI 摘要",
            )
        )
        self.assertTrue(
            self.repository.update_workflow_status(
                queue_number,
                "summary_ready",
            )
        )

        record = self.repository.get(queue_number)
        self.assertEqual(record["report"], "背景產生的 AI 摘要")
        self.assertEqual(record["status"], "summary_ready")
        self.assertEqual(record["summary_error"], "")

    def test_delete_permanently_removes_consultation(self):
        queue_number = self.repository.create(
            {
                "type": "headache",
                "summary": "頭痛摘要",
                "report": "初步報告",
                "data": {"name": "待刪除病人"},
            }
        )

        self.assertTrue(self.repository.delete(queue_number))
        self.assertIsNone(self.repository.get(queue_number))
        self.assertEqual(self.repository.count(), 0)
        self.assertFalse(self.repository.delete(queue_number))


if __name__ == "__main__":
    unittest.main()
