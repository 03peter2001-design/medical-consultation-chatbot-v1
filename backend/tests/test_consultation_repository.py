import gc
import multiprocessing
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from infrastructure.consultation_repository import SCHEMA_VERSION, ConsultationRepository


def _run_repository_initialization(
    database_path,
    start_event,
    result_queue,
    ready_queue=None,
):
    """Initialize one independent connection after all workers are ready."""
    if ready_queue is not None:
        ready_queue.put(None)
    start_event.wait(timeout=10)
    try:
        ConsultationRepository(database_path)
    except Exception as error:  # pragma: no cover - reported in the parent process
        result_queue.put(f"{type(error).__name__}: {error}")
    else:
        result_queue.put(None)


class ConsultationRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "consultations.db"
        self.repository = ConsultationRepository(self.database_path)

    def tearDown(self):
        del self.repository
        gc.collect()
        self.temp_directory.cleanup()

    def test_wal_setup_retries_only_lock_contention_and_has_wal_fast_path(self):
        def journal_mode_result(mode):
            result = Mock()
            result.fetchone.return_value = (mode,)
            return result

        contended_connection = Mock()
        contended_connection.execute.side_effect = [
            journal_mode_result("delete"),
            sqlite3.OperationalError("database is locked"),
            journal_mode_result("wal"),
        ]
        with patch("infrastructure.consultation_repository.time.sleep") as sleep:
            ConsultationRepository._enable_write_ahead_log(contended_connection)

        self.assertEqual(
            [call.args[0] for call in contended_connection.execute.call_args_list],
            ["PRAGMA journal_mode", "PRAGMA journal_mode = WAL", "PRAGMA journal_mode"],
        )
        sleep.assert_called_once()

        wal_connection = Mock()
        wal_connection.execute.return_value = journal_mode_result("wal")
        ConsultationRepository._enable_write_ahead_log(wal_connection)
        wal_connection.execute.assert_called_once_with("PRAGMA journal_mode")

        broken_connection = Mock()
        disk_error = sqlite3.OperationalError("disk I/O error")
        broken_connection.execute.side_effect = [
            journal_mode_result("delete"),
            disk_error,
        ]
        with self.assertRaises(sqlite3.OperationalError) as raised:
            ConsultationRepository._enable_write_ahead_log(broken_connection)
        self.assertIs(raised.exception, disk_error)
        self.assertEqual(broken_connection.execute.call_count, 2)

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

        created = self.repository.create_with_identifiers(record)
        queue_number = created["queue_number"]
        # A new repository instance represents reading after an app restart.
        reopened_repository = ConsultationRepository(self.database_path)
        saved = reopened_repository.get(created["consultation_id"])

        self.assertRegex(queue_number, r"^\d{3}$")
        self.assertEqual(queue_number, "000")
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
        created = self.repository.create_with_identifiers(
            {
                "type": "headache",
                "summary": "摘要",
                "report": "報告",
                "data": {},
                "triage_level": "routine",
            }
        )

        queue_number = created["queue_number"]
        self.assertEqual(queue_number, "10000")
        self.assertEqual(
            self.repository.get(created["consultation_id"])["queue_number"],
            queue_number,
        )

    def test_fixed_synthetic_record_is_idempotently_updated(self):
        consultation_id = self.repository.upsert_fixed(
            "00000",
            {
                "type": "chest",
                "summary": "舊摘要",
                "report": "舊報告",
                "data": {},
            },
        )
        consultation_id = self.repository.upsert_fixed(
            "00000",
            {
                "type": "headache",
                "summary": "新摘要",
                "report": "新報告",
                "data": {"reason": "頭痛"},
                "status": "synthetic_test",
            },
        )

        saved = self.repository.get(consultation_id)
        self.assertEqual(self.repository.count(), 1)
        self.assertEqual(saved["type"], "headache")
        self.assertEqual(saved["summary"], "新摘要")
        self.assertEqual(saved["data"], {"reason": "頭痛"})
        self.assertEqual(
            self.repository.get_by_registration_number("00000")["consultation_id"],
            consultation_id,
        )

    def test_registration_lookup_never_matches_hidden_queue_number(self):
        with patch.object(
            ConsultationRepository,
            "_queue_number",
            side_effect=["54321", "10000"],
        ):
            first = self.repository.create_with_identifiers(
                {
                    "type": "headache",
                    "summary": "掛號 10000，隱藏鍵 54321",
                    "report": "first",
                    "data": {"name": "病人 A"},
                }
            )
            connection = self.repository._connect()
            try:
                with connection:
                    connection.execute(
                        """
                        UPDATE consultation_number_sequences
                        SET next_number = 54321
                        WHERE consultation_date = ? AND triage_level = 'routine'
                        """,
                        (first["consultation_date"],),
                    )
            finally:
                connection.close()
            second = self.repository.create_with_identifiers(
                {
                    "type": "headache",
                    "summary": "掛號 54321，隱藏鍵 10000",
                    "report": "second",
                    "data": {"name": "病人 B"},
                }
            )

        self.assertEqual(first["queue_number"], "10000")
        self.assertEqual(second["queue_number"], "54321")
        connection = self.repository._connect()
        try:
            identifiers = connection.execute(
                """
                SELECT display_number, queue_number
                FROM consultations
                ORDER BY id
                """
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(
            [(row["display_number"], row["queue_number"]) for row in identifiers],
            [("10000", "54321"), ("54321", "10000")],
        )
        self.assertEqual(
            self.repository.get_by_registration_number("10000")["data"]["name"],
            "病人 A",
        )
        self.assertEqual(
            self.repository.get_by_registration_number("54321")["data"]["name"],
            "病人 B",
        )

    def test_database_file_is_owner_only(self):
        if os.name == "nt":
            self.skipTest("POSIX file permissions are not available")
        mode = self.database_path.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_missing_queue_number_returns_none(self):
        self.assertIsNone(self.repository.get("2026-01-01:12345"))

    def test_consultation_id_parser_accepts_exact_ascii_boundaries(self):
        accepted = {
            "2024-02-29:000": ("2024-02-29", "000"),
            "2026-08-05:999": ("2026-08-05", "999"),
            "2026-08-05:10000": ("2026-08-05", "10000"),
            "2026-08-05:99999": ("2026-08-05", "99999"),
        }

        for consultation_id, expected in accepted.items():
            with self.subTest(consultation_id=consultation_id):
                self.assertEqual(
                    self.repository._parse_consultation_id(consultation_id),
                    expected,
                )
                self.assertEqual(
                    self.repository.consultation_id(*expected),
                    consultation_id,
                )

    def test_consultation_id_parser_rejects_noncanonical_formats(self):
        rejected = [
            "20260805:001",
            "2026-W32-3:001",
            "2026-08-05:００１",
            "2026-08-05:01",
            "2026-08-05:0001",
            "2026-08-05:000001",
            " 2026-08-05:001",
            "2026-08-05:001 ",
            "2026-08-05:001\n",
            "2026-08-05:001:extra",
        ]

        for consultation_id in rejected:
            with (
                self.subTest(consultation_id=consultation_id),
                self.assertRaisesRegex(ValueError, "ASCII YYYY-MM-DD"),
            ):
                self.repository._parse_consultation_id(consultation_id)

    def test_consultation_id_parser_rejects_invalid_calendar_dates(self):
        for consultation_id in (
            "2023-02-29:001",
            "2026-04-31:001",
            "2026-13-01:001",
        ):
            with (
                self.subTest(consultation_id=consultation_id),
                self.assertRaisesRegex(ValueError, "有效的 calendar date"),
            ):
                self.repository._parse_consultation_id(consultation_id)

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
        created = self.repository.create_with_identifiers(
            {
                "type": "abdomen",
                "summary": "腹痛摘要",
                "report": "初步報告",
                "data": {"name": "林先生"},
            }
        )

        saved = self.repository.save_structured_note(
            created["consultation_id"],
            "六段式 AI 總結",
            [{"title": "Abdominal Pain", "url": "https://example.test"}],
        )
        reopened = ConsultationRepository(self.database_path)
        record = reopened.get(created["consultation_id"])
        summary = reopened.list_summaries(search=created["queue_number"])["items"][0]

        self.assertTrue(saved)
        self.assertEqual(record["structured_note"], "六段式 AI 總結")
        self.assertEqual(
            record["structured_sources"][0]["title"],
            "Abdominal Pain",
        )
        self.assertTrue(record["structured_note_created_at"])
        self.assertTrue(summary["has_structured_note"])

    def test_async_summary_status_and_report_can_be_updated(self):
        created = self.repository.create_with_identifiers(
            {
                "type": "headache",
                "summary": "患者資料已保存",
                "report": "摘要產生中",
                "data": {"name": "陳小姐"},
                "status": "summary_pending",
            }
        )

        self.assertEqual(
            self.repository.get(created["consultation_id"])["status"],
            "summary_pending",
        )
        self.assertTrue(
            self.repository.save_generated_report(
                created["consultation_id"],
                "背景產生的 AI 摘要",
            )
        )
        self.assertTrue(
            self.repository.update_workflow_status(
                created["consultation_id"],
                "summary_ready",
            )
        )

        record = self.repository.get(created["consultation_id"])
        self.assertEqual(record["report"], "背景產生的 AI 摘要")
        self.assertEqual(record["status"], "summary_ready")
        self.assertEqual(record["summary_error"], "")

    def test_delete_permanently_removes_consultation(self):
        created = self.repository.create_with_identifiers(
            {
                "type": "headache",
                "summary": "頭痛摘要",
                "report": "初步報告",
                "data": {"name": "待刪除病人"},
            }
        )

        self.assertTrue(self.repository.delete(created["consultation_id"]))
        self.assertIsNone(self.repository.get(created["consultation_id"]))
        self.assertEqual(self.repository.count(), 0)
        self.assertFalse(self.repository.delete(created["consultation_id"]))

    def test_daily_sequences_restart_and_composite_ids_keep_records_distinct(self):
        current = [datetime(2026, 8, 4, 16, 5, tzinfo=timezone.utc)]
        repository = ConsultationRepository(
            self.database_path,
            now_provider=lambda: current[0],
        )

        urgent_first = repository.create_with_identifiers(
            {
                "type": "chest",
                "summary": "第一天急診一",
                "report": "pending",
                "data": {"name": "前日 000"},
                "triage_level": "urgent",
            }
        )
        urgent_second = repository.create_with_identifiers(
            {
                "type": "chest",
                "summary": "第一天急診二",
                "report": "pending",
                "data": {},
                "triage_level": "urgent",
            }
        )
        routine_first = repository.create_with_identifiers(
            {
                "type": "headache",
                "summary": "第一天普通一",
                "report": "pending",
                "data": {},
            }
        )
        routine_second = repository.create_with_identifiers(
            {
                "type": "headache",
                "summary": "第一天普通二",
                "report": "pending",
                "data": {},
            }
        )

        self.assertEqual(urgent_first["queue_number"], "000")
        self.assertEqual(urgent_second["queue_number"], "001")
        self.assertEqual(routine_first["queue_number"], "10000")
        self.assertEqual(routine_second["queue_number"], "10001")
        self.assertEqual(urgent_first["consultation_date"], "2026-08-05")
        self.assertTrue(repository.delete(routine_second["consultation_id"]))
        routine_after_delete = repository.create_with_identifiers(
            {
                "type": "headache",
                "summary": "刪除後普通病例",
                "report": "pending",
                "data": {},
            }
        )
        self.assertEqual(routine_after_delete["queue_number"], "10002")

        current[0] = datetime(2026, 8, 5, 16, 5, tzinfo=timezone.utc)
        next_day = repository.create_with_identifiers(
            {
                "type": "chest",
                "summary": "第二天急診一",
                "report": "pending",
                "data": {"name": "今日 000"},
                "triage_level": "urgent",
            }
        )
        self.assertEqual(next_day["queue_number"], "000")
        self.assertEqual(next_day["consultation_date"], "2026-08-06")
        self.assertNotEqual(next_day["consultation_id"], urgent_first["consultation_id"])

        repository.save_generated_report(
            urgent_first["consultation_id"],
            "昨天的報告",
        )
        repository.save_generated_report(next_day["consultation_id"], "今天的報告")
        self.assertEqual(
            repository.get(urgent_first["consultation_id"])["report"],
            "昨天的報告",
        )
        self.assertEqual(
            repository.get(next_day["consultation_id"])["report"],
            "今天的報告",
        )
        with self.assertRaisesRegex(ValueError, "跨日期重複"):
            repository.get_by_registration_number("000")
        self.assertTrue(repository.delete(urgent_first["consultation_id"]))
        self.assertIsNotNone(repository.get(next_day["consultation_id"]))

    def test_legacy_database_backfills_taipei_date_and_stable_composite_id(self):
        legacy_path = Path(self.temp_directory.name) / "legacy.db"
        with sqlite3.connect(legacy_path) as connection:
            connection.executescript(
                """
                CREATE TABLE consultations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_number TEXT NOT NULL UNIQUE,
                    display_number TEXT NOT NULL,
                    session_id TEXT,
                    patient_name TEXT,
                    consultation_type TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL,
                    report TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    structured_note TEXT,
                    structured_sources_json TEXT NOT NULL DEFAULT '[]',
                    structured_note_created_at TEXT,
                    summary_error TEXT,
                    triage_level TEXT NOT NULL DEFAULT 'routine',
                    workflow_status TEXT NOT NULL DEFAULT 'completed',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO consultations (
                    queue_number, display_number, consultation_type, summary,
                    report, data_json, triage_level, created_at, updated_at
                ) VALUES (
                    '54321', '001', 'chest', 'legacy', 'legacy report', '{}',
                    'urgent', '2026-08-04T16:30:00+00:00',
                    '2026-08-04T16:30:00+00:00'
                );
                PRAGMA user_version = 5;
                """
            )

        def migration_now():
            return datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)

        migrated = ConsultationRepository(legacy_path, now_provider=migration_now)
        record = migrated.get("2026-08-05:001")
        self.assertIsNotNone(record)
        self.assertEqual(record["consultation_date"], "2026-08-05")
        self.assertEqual(record["consultation_id"], "2026-08-05:001")
        next_record = migrated.create_with_identifiers(
            {
                "type": "chest",
                "summary": "migration 後的新病例",
                "report": "pending",
                "data": {},
                "triage_level": "urgent",
            }
        )
        self.assertEqual(next_record["queue_number"], "002")
        reopened = ConsultationRepository(legacy_path, now_provider=migration_now)
        self.assertEqual(
            reopened.get("2026-08-05:001")["consultation_id"],
            record["consultation_id"],
        )
        with sqlite3.connect(legacy_path) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0],
                SCHEMA_VERSION,
            )
            self.assertEqual(
                connection.execute(
                    """
                    SELECT count(*)
                    FROM consultation_number_sequences
                    WHERE consultation_date = '2026-08-05'
                      AND triage_level = 'urgent'
                      AND next_number = 3
                    """
                ).fetchone()[0],
                1,
            )

    def test_v5_migration_is_safe_across_eight_concurrent_processes(self):
        context = multiprocessing.get_context("spawn")
        for stress_round in range(3):
            legacy_path = Path(self.temp_directory.name) / f"concurrent-v5-{stress_round}.db"
            with sqlite3.connect(legacy_path) as connection:
                connection.executescript(
                    """
                CREATE TABLE consultations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_number TEXT NOT NULL UNIQUE,
                    display_number TEXT NOT NULL,
                    session_id TEXT,
                    patient_name TEXT,
                    consultation_type TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL,
                    report TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    structured_note TEXT,
                    structured_sources_json TEXT NOT NULL DEFAULT '[]',
                    structured_note_created_at TEXT,
                    summary_error TEXT,
                    triage_level TEXT NOT NULL DEFAULT 'routine',
                    workflow_status TEXT NOT NULL DEFAULT 'completed',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO consultations (
                    queue_number, display_number, consultation_type, summary,
                    report, data_json, triage_level, created_at, updated_at
                ) VALUES (
                    '54321', '001', 'chest', 'legacy', 'legacy report', '{}',
                    'urgent', '2026-08-04T16:30:00+00:00',
                    '2026-08-04T16:30:00+00:00'
                );
                PRAGMA user_version = 5;
                """
                )

            # Keep a rollback-journal reader open while all workers first try
            # to switch the database to WAL. This forces the PRAGMA lock race
            # that occurs during a multi-worker application cold start.
            blocking_reader = sqlite3.connect(legacy_path)
            blocking_reader.execute("BEGIN")
            blocking_reader.execute("SELECT count(*) FROM consultations").fetchone()

            start_event = context.Event()
            ready_queue = context.Queue()
            result_queue = context.Queue()
            workers = [
                context.Process(
                    target=_run_repository_initialization,
                    args=(
                        str(legacy_path),
                        start_event,
                        result_queue,
                        ready_queue,
                    ),
                )
                for _ in range(8)
            ]
            try:
                for worker in workers:
                    worker.start()
                for _ in workers:
                    ready_queue.get(timeout=10)
                start_event.set()
                time.sleep(0.25)
            finally:
                blocking_reader.rollback()
                blocking_reader.close()

            for worker in workers:
                worker.join(timeout=20)
            hanging_workers = [worker for worker in workers if worker.is_alive()]
            for worker in hanging_workers:
                worker.terminate()
                worker.join(timeout=5)

            with self.subTest(stress_round=stress_round):
                self.assertEqual(hanging_workers, [])
                self.assertEqual(
                    [result_queue.get(timeout=5) for _ in workers],
                    [None] * 8,
                )
                self.assertEqual([worker.exitcode for worker in workers], [0] * 8)

            with sqlite3.connect(legacy_path) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(consultations)")}
                self.assertIn("consultation_date", columns)
                self.assertEqual(
                    connection.execute("PRAGMA user_version").fetchone()[0],
                    SCHEMA_VERSION,
                )
                self.assertEqual(
                    connection.execute("SELECT consultation_date FROM consultations").fetchone()[0],
                    "2026-08-05",
                )
                self.assertEqual(
                    connection.execute(
                        """
                    SELECT next_number
                    FROM consultation_number_sequences
                    WHERE consultation_date = '2026-08-05'
                      AND triage_level = 'urgent'
                    """
                    ).fetchone()[0],
                    2,
                )

    def test_failed_v5_migration_rolls_back_schema_data_and_version(self):
        legacy_path = Path(self.temp_directory.name) / "failed-v5.db"
        with sqlite3.connect(legacy_path) as connection:
            connection.executescript(
                """
                CREATE TABLE consultations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_number TEXT NOT NULL UNIQUE,
                    display_number TEXT NOT NULL,
                    session_id TEXT,
                    patient_name TEXT,
                    consultation_type TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL,
                    report TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    structured_note TEXT,
                    structured_sources_json TEXT NOT NULL DEFAULT '[]',
                    structured_note_created_at TEXT,
                    summary_error TEXT,
                    triage_level TEXT NOT NULL DEFAULT 'routine',
                    workflow_status TEXT NOT NULL DEFAULT 'completed',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO consultations (
                    queue_number, display_number, consultation_type, summary,
                    report, data_json, triage_level, created_at, updated_at
                ) VALUES (
                    '54321', '001', 'chest', 'legacy', 'legacy report', '{}',
                    'urgent', '2026-08-04T16:30:00+00:00',
                    '2026-08-04T16:30:00+00:00'
                );
                INSERT INTO consultations (
                    queue_number, display_number, consultation_type, summary,
                    report, data_json, triage_level, created_at, updated_at
                ) VALUES (
                    '54322', '001', 'chest', 'legacy collision',
                    'legacy report', '{}', 'urgent',
                    '2026-08-04T16:31:00+00:00',
                    '2026-08-04T16:31:00+00:00'
                );
                PRAGMA user_version = 5;
                """
            )

        original_migrate_schema = ConsultationRepository._migrate_schema

        def fail_after_complete_migration(repository, connection):
            original_migrate_schema(repository, connection)
            raise RuntimeError("injected migration failure")

        with (
            patch.object(
                ConsultationRepository,
                "_migrate_schema",
                new=fail_after_complete_migration,
            ),
            self.assertRaisesRegex(RuntimeError, "injected migration failure"),
        ):
            ConsultationRepository(legacy_path)

        with sqlite3.connect(legacy_path) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(consultations)")}
            objects = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
                )
            }
            self.assertNotIn("consultation_date", columns)
            self.assertNotIn("consultation_number_sequences", objects)
            self.assertNotIn("idx_consultations_date_registration", objects)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertEqual(
                connection.execute(
                    "SELECT display_number FROM consultations ORDER BY id"
                ).fetchall(),
                [("001",), ("001",)],
            )

        migrated = ConsultationRepository(legacy_path)
        self.assertIsNotNone(migrated.get("2026-08-05:001"))
        with sqlite3.connect(legacy_path) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0],
                SCHEMA_VERSION,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT count(DISTINCT display_number) FROM consultations"
                ).fetchone()[0],
                2,
            )


if __name__ == "__main__":
    unittest.main()
