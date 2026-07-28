"""Persistent storage for completed consultation results.

SQLite is used by default so local development needs no separate database
service.  Each operation opens a short-lived connection, which is safe for
FastAPI's worker threads and keeps the repository easy to replace later.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 5
URGENT_NUMBER_ACTIVE_HOURS = 8
BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = BACKEND_DIR / "data" / "consultations.db"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _resolve_database_path(value: str | None) -> Path:
    if not value:
        return DEFAULT_DATABASE_PATH
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = BACKEND_DIR / path
    return path.resolve()


class ConsultationRepository:
    """Store and retrieve immutable consultation results by queue number."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        if self.database_path == DEFAULT_DATABASE_PATH:
            try:
                os.chmod(self.database_path.parent, 0o700)
            except OSError:
                pass
        self._initialize()

    @classmethod
    def from_environment(cls) -> "ConsultationRepository":
        return cls(_resolve_database_path(os.getenv("CONSULTATION_DB_PATH")))

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=10,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS consultations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_number TEXT NOT NULL UNIQUE
                        CHECK (
                            length(queue_number) = 5
                            AND queue_number NOT GLOB '*[^0-9]*'
                        ),
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
                    triage_level TEXT NOT NULL DEFAULT 'routine'
                        CHECK (triage_level IN ('routine', 'urgent')),
                    workflow_status TEXT NOT NULL DEFAULT 'completed',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS
                    idx_consultations_type_created_at
                    ON consultations (consultation_type, created_at DESC);

                CREATE INDEX IF NOT EXISTS
                    idx_consultations_status_created_at
                    ON consultations (workflow_status, created_at DESC);
                """
            )

            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(consultations)").fetchall()
            }
            if "patient_name" not in columns:
                connection.execute("ALTER TABLE consultations ADD COLUMN patient_name TEXT")
                rows = connection.execute("SELECT id, data_json FROM consultations").fetchall()
                backfill = []
                for row in rows:
                    try:
                        data = json.loads(row["data_json"])
                    except (TypeError, json.JSONDecodeError):
                        data = {}
                    backfill.append((data.get("name"), row["id"]))
                connection.executemany(
                    """
                    UPDATE consultations
                    SET patient_name = ?
                    WHERE id = ?
                    """,
                    backfill,
                )
            if "display_number" not in columns:
                connection.execute("ALTER TABLE consultations ADD COLUMN display_number TEXT")
                connection.execute(
                    """
                    UPDATE consultations
                    SET display_number = queue_number
                    WHERE display_number IS NULL
                    """
                )
            if "structured_note" not in columns:
                connection.execute("ALTER TABLE consultations ADD COLUMN structured_note TEXT")
            if "structured_sources_json" not in columns:
                connection.execute(
                    """
                    ALTER TABLE consultations
                    ADD COLUMN structured_sources_json
                    TEXT NOT NULL DEFAULT '[]'
                    """
                )
            if "structured_note_created_at" not in columns:
                connection.execute(
                    """
                    ALTER TABLE consultations
                    ADD COLUMN structured_note_created_at TEXT
                    """
                )
            if "summary_error" not in columns:
                connection.execute("ALTER TABLE consultations ADD COLUMN summary_error TEXT")

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_consultations_display_created_at
                    ON consultations (display_number, created_at DESC)
                """
            )

            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

        # Consultation data can contain protected health information.  Restrict
        # the local database file to its owner where the platform supports it.
        try:
            os.chmod(self.database_path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _serialize_data(data: dict[str, Any]) -> str:
        if not isinstance(data, dict):
            raise ValueError("consultation data must be a JSON object")
        return json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _queue_number() -> str:
        # 00000 is reserved for the built-in synthetic test patient.
        return f"{secrets.randbelow(99_999) + 1:05d}"

    @staticmethod
    def _urgent_display_number(
        connection: sqlite3.Connection,
        now: str,
    ) -> str:
        """Return an unused three-digit number in the active care window."""
        cutoff = (
            datetime.fromisoformat(now) - timedelta(hours=URGENT_NUMBER_ACTIVE_HOURS)
        ).isoformat(timespec="milliseconds")
        for _ in range(128):
            display_number = f"{secrets.randbelow(999) + 1:03d}"
            exists = connection.execute(
                """
                SELECT 1
                FROM consultations
                WHERE display_number = ?
                  AND triage_level = 'urgent'
                  AND created_at >= ?
                LIMIT 1
                """,
                (display_number, cutoff),
            ).fetchone()
            if exists is None:
                return display_number
        raise RuntimeError("無法產生未使用的緊急問診編號")

    def create(self, record: dict[str, Any]) -> str:
        """Insert a result and return its patient-facing queue number."""
        data_json = self._serialize_data(record.get("data", {}))
        now = _utc_now()
        triage_level = record.get("triage_level", "routine")

        for _ in range(64):
            queue_number = self._queue_number()
            try:
                with self._connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    display_number = (
                        self._urgent_display_number(connection, now)
                        if triage_level == "urgent"
                        else queue_number
                    )
                    connection.execute(
                        """
                        INSERT INTO consultations (
                            queue_number,
                            display_number,
                            session_id,
                            patient_name,
                            consultation_type,
                            reason,
                            summary,
                            report,
                            data_json,
                            triage_level,
                            workflow_status,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            queue_number,
                            display_number,
                            record.get("session_id"),
                            record.get("data", {}).get("name"),
                            record.get("type", "other"),
                            record.get("reason", ""),
                            record.get("summary", ""),
                            record.get("report", ""),
                            data_json,
                            triage_level,
                            record.get("status", "completed"),
                            now,
                            now,
                        ),
                    )
                return display_number
            except sqlite3.IntegrityError as error:
                if "queue_number" not in str(error):
                    raise

        raise RuntimeError("無法產生未使用的問診編號")

    def upsert_fixed(
        self,
        queue_number: str,
        record: dict[str, Any],
    ) -> None:
        """Insert or refresh a fixed record, used only for synthetic fixtures."""
        if len(queue_number) != 5 or not queue_number.isdigit():
            raise ValueError("queue_number must contain exactly five digits")
        data_json = self._serialize_data(record.get("data", {}))
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO consultations (
                    queue_number,
                    display_number,
                    session_id,
                    patient_name,
                    consultation_type,
                    reason,
                    summary,
                    report,
                    data_json,
                    triage_level,
                    workflow_status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(queue_number) DO UPDATE SET
                    display_number = excluded.display_number,
                    session_id = excluded.session_id,
                    patient_name = excluded.patient_name,
                    consultation_type = excluded.consultation_type,
                    reason = excluded.reason,
                    summary = excluded.summary,
                    report = excluded.report,
                    data_json = excluded.data_json,
                    triage_level = excluded.triage_level,
                    workflow_status = excluded.workflow_status,
                    updated_at = excluded.updated_at
                """,
                (
                    queue_number,
                    queue_number,
                    record.get("session_id"),
                    record.get("data", {}).get("name"),
                    record.get("type", "other"),
                    record.get("reason", ""),
                    record.get("summary", ""),
                    record.get("report", ""),
                    data_json,
                    record.get("triage_level", "routine"),
                    record.get("status", "completed"),
                    now,
                    now,
                ),
            )

    def get(self, queue_number: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    queue_number,
                    display_number,
                    session_id,
                    consultation_type,
                    reason,
                    summary,
                    report,
                    data_json,
                    structured_note,
                    structured_sources_json,
                    structured_note_created_at,
                    summary_error,
                    triage_level,
                    workflow_status,
                    created_at,
                    updated_at
                FROM consultations
                WHERE display_number = ? OR queue_number = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (queue_number, queue_number),
            ).fetchone()

        if row is None:
            return None
        return {
            "queue_number": row["display_number"],
            "session_id": row["session_id"],
            "type": row["consultation_type"],
            "reason": row["reason"],
            "summary": row["summary"],
            "report": row["report"],
            "data": json.loads(row["data_json"]),
            "structured_note": row["structured_note"],
            "structured_sources": json.loads(row["structured_sources_json"] or "[]"),
            "structured_note_created_at": row["structured_note_created_at"],
            "summary_error": row["summary_error"] or "",
            "triage_level": row["triage_level"],
            "status": row["workflow_status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_summaries(
        self,
        *,
        search: str = "",
        limit: int = 30,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return paginated metadata without exposing reports or full answers."""
        safe_limit = max(1, min(int(limit), 100))
        safe_offset = max(0, int(offset))
        normalized_search = search.strip()[:100]
        where_sql = ""
        where_params: tuple[str, ...] = ()
        if normalized_search:
            pattern = f"%{normalized_search}%"
            where_sql = """
                WHERE (
                    display_number LIKE ?
                    OR queue_number LIKE ?
                    OR coalesce(patient_name, '') LIKE ?
                    OR reason LIKE ?
                )
            """
            where_params = (pattern, pattern, pattern, pattern)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    queue_number,
                    display_number,
                    patient_name,
                    consultation_type,
                    reason,
                    data_json,
                    triage_level,
                    workflow_status,
                    structured_note,
                    created_at
                FROM consultations
                {where_sql}
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (*where_params, safe_limit, safe_offset),
            ).fetchall()
            total_row = connection.execute(
                f"""
                SELECT count(*) AS total
                FROM consultations
                {where_sql}
                """,
                where_params,
            ).fetchone()

        items = []
        for row in rows:
            try:
                data = json.loads(row["data_json"])
            except (TypeError, json.JSONDecodeError):
                data = {}
            items.append(
                {
                    "queue_number": row["display_number"],
                    "patient_name": row["patient_name"] or "未提供",
                    "type": row["consultation_type"],
                    "reason": row["reason"],
                    "gender": data.get("gender", "未提供"),
                    "age": data.get("age", "未提供"),
                    "triage_level": row["triage_level"],
                    "workflow_status": row["workflow_status"],
                    "has_structured_note": bool(row["structured_note"]),
                    "created_at": row["created_at"],
                }
            )

        return {
            "items": items,
            "total": int(total_row["total"]),
            "limit": safe_limit,
            "offset": safe_offset,
        }

    def save_structured_note(
        self,
        queue_number: str,
        note: str,
        sources: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Persist the generated physician summary for future loads."""
        normalized_note = note.strip()
        if not normalized_note:
            raise ValueError("structured note must not be empty")
        if sources is not None and not isinstance(sources, list):
            raise ValueError("structured note sources must be a list")
        sources_json = json.dumps(
            sources or [],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        now = _utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE consultations
                SET structured_note = ?,
                    structured_sources_json = ?,
                    structured_note_created_at = ?,
                    updated_at = ?
                WHERE id = (
                    SELECT id
                    FROM consultations
                    WHERE display_number = ? OR queue_number = ?
                    ORDER BY id DESC
                    LIMIT 1
                )
                """,
                (
                    normalized_note,
                    sources_json,
                    now,
                    now,
                    queue_number,
                    queue_number,
                ),
            )
        return cursor.rowcount == 1

    def save_generated_report(
        self,
        queue_number: str,
        report: str,
    ) -> bool:
        """Persist an AI report generated after the patient got a number."""
        normalized_report = report.strip()
        if not normalized_report:
            raise ValueError("generated report must not be empty")
        now = _utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE consultations
                SET report = ?,
                    updated_at = ?
                WHERE id = (
                    SELECT id
                    FROM consultations
                    WHERE display_number = ? OR queue_number = ?
                    ORDER BY id DESC
                    LIMIT 1
                )
                """,
                (
                    normalized_report,
                    now,
                    queue_number,
                    queue_number,
                ),
            )
        return cursor.rowcount == 1

    def update_workflow_status(
        self,
        queue_number: str,
        status: str,
        *,
        error: str = "",
    ) -> bool:
        """Update asynchronous summary state without changing case data."""
        normalized_status = status.strip()[:64]
        if not normalized_status:
            raise ValueError("workflow status must not be empty")
        normalized_error = error.strip()[:1000] or None
        now = _utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE consultations
                SET workflow_status = ?,
                    summary_error = ?,
                    updated_at = ?
                WHERE id = (
                    SELECT id
                    FROM consultations
                    WHERE display_number = ? OR queue_number = ?
                    ORDER BY id DESC
                    LIMIT 1
                )
                """,
                (
                    normalized_status,
                    normalized_error,
                    now,
                    queue_number,
                    queue_number,
                ),
            )
        return cursor.rowcount == 1

    def delete(self, queue_number: str) -> bool:
        """Permanently delete the newest record matching a display number."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM consultations
                WHERE id = (
                    SELECT id
                    FROM consultations
                    WHERE display_number = ? OR queue_number = ?
                    ORDER BY id DESC
                    LIMIT 1
                )
                """,
                (queue_number, queue_number),
            )
        return cursor.rowcount == 1

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT count(*) AS total FROM consultations").fetchone()
        return int(row["total"])
