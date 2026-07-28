import tempfile
import unittest
from pathlib import Path

from app.services.consultation_service import (
    get_or_create_structured_note,
    process_consultation_summaries,
)
from infrastructure.consultation_repository import ConsultationRepository


class ConsultationServiceTests(unittest.TestCase):
    def test_submission_generation_is_persisted_and_reused(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = ConsultationRepository(Path(temporary_directory) / "consultations.db")
            queue_number = repository.create(
                {
                    "type": "chest",
                    "summary": "胸痛摘要",
                    "report": "初步報告",
                    "data": {"name": "王小明"},
                }
            )
            calls = []

            def generator(record):
                calls.append(record["queue_number"])
                return (
                    "已產生並儲存的 AI 總結",
                    [{"title": "Chest Pain"}],
                )

            first = get_or_create_structured_note(
                repository,
                repository.get(queue_number),
                generator,
            )
            second = get_or_create_structured_note(
                repository,
                repository.get(queue_number),
                generator,
            )

            self.assertEqual(first, second)
            self.assertEqual(calls, [queue_number])
            self.assertEqual(
                second[0],
                "已產生並儲存的 AI 總結",
            )

    def test_number_exists_before_background_generators_run(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = ConsultationRepository(Path(temporary_directory) / "consultations.db")
            queue_number = repository.create(
                {
                    "type": "headache",
                    "summary": "問卷資料",
                    "report": "摘要產生中",
                    "data": {"name": "測試病人"},
                    "triage_level": "urgent",
                    "status": "summary_pending",
                }
            )
            events = []

            def report_generator(record):
                events.append(("report", record["status"]))
                self.assertEqual(record["queue_number"], queue_number)
                self.assertIsNotNone(repository.get(queue_number))
                return "urgent 病人的 AI 預問診摘要"

            def structured_generator(record):
                events.append(("structured", record["report"]))
                return "urgent 病人的六段式摘要", []

            status = process_consultation_summaries(
                repository,
                queue_number,
                report_generator,
                structured_generator,
                structured_note_expected=True,
            )

            saved = repository.get(queue_number)
            self.assertEqual(status, "summary_ready")
            self.assertEqual(saved["status"], "summary_ready")
            self.assertEqual(
                saved["report"],
                "urgent 病人的 AI 預問診摘要",
            )
            self.assertEqual(
                saved["structured_note"],
                "urgent 病人的六段式摘要",
            )
            self.assertEqual(
                events,
                [
                    ("report", "summary_pending"),
                    ("structured", "urgent 病人的 AI 預問診摘要"),
                ],
            )

    def test_background_failure_is_persisted_without_losing_number(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = ConsultationRepository(Path(temporary_directory) / "consultations.db")
            queue_number = repository.create(
                {
                    "type": "chest",
                    "summary": "問卷資料",
                    "report": "摘要產生中",
                    "data": {},
                    "status": "summary_pending",
                }
            )

            status = process_consultation_summaries(
                repository,
                queue_number,
                lambda record: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
                lambda record: (None, []),
                structured_note_expected=False,
            )

            saved = repository.get(queue_number)
            self.assertEqual(status, "summary_failed")
            self.assertEqual(saved["status"], "summary_failed")
            self.assertIn("RuntimeError", saved["summary_error"])
            self.assertEqual(saved["queue_number"], queue_number)


if __name__ == "__main__":
    unittest.main()
