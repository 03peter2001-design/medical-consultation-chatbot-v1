"""Persistent storage for completed consultation results.

SQLite is used by default so local development needs no separate database
service.  Each operation opens a short-lived connection, which is safe for
FastAPI's worker threads and keeps the repository easy to replace later.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA_VERSION = 9
DEFAULT_CONSULTATION_TIMEZONE = "Asia/Taipei"
BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = BACKEND_DIR / "data" / "consultations.db"
CONSULTATION_ID_PATTERN = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2}):([0-9]{3}|[0-9]{5})")
CONSULTATION_ID_FORMAT_ERROR = "consultation_id 格式必須為 ASCII YYYY-MM-DD:NNN 或 YYYY-MM-DD:NNNNN"
CONSULTATION_ID_DATE_ERROR = "consultation_id 日期必須是有效的 calendar date"
SQLITE_LOCK_TIMEOUT_SECONDS = 10.0
SQLITE_BUSY_TIMEOUT_MILLISECONDS = int(SQLITE_LOCK_TIMEOUT_SECONDS * 1_000)
WAL_RETRY_INITIAL_DELAY_SECONDS = 0.005
WAL_RETRY_MAX_DELAY_SECONDS = 0.1
MAX_PATIENT_RUNTIME_STATE_BYTES = 512 * 1024
AUDIT_RETENTION_DAYS = max(1, int(os.getenv("AUDIT_RETENTION_DAYS", "90")))
AUDIT_MAX_ROWS = max(1_000, int(os.getenv("AUDIT_MAX_ROWS", "100000")))


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
    """Store consultations by permanent ID and allocate local-day display numbers."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        timezone_name: str | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.database_path = Path(database_path).resolve()
        self.timezone_name = timezone_name or os.getenv(
            "CONSULTATION_TIMEZONE",
            DEFAULT_CONSULTATION_TIMEZONE,
        )
        try:
            self.local_timezone = ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown consultation timezone: {self.timezone_name}") from error
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
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
            timeout=SQLITE_LOCK_TIMEOUT_SECONDS,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MILLISECONDS}")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @staticmethod
    def _is_sqlite_lock_error(error: sqlite3.OperationalError) -> bool:
        """Return whether SQLite identified this operation as lock contention."""
        error_code = getattr(error, "sqlite_errorcode", None)
        if error_code is not None:
            primary_error_code = error_code & 0xFF
            return primary_error_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
        return str(error).casefold() in {
            "database is locked",
            "database table is locked",
        }

    @classmethod
    def _enable_write_ahead_log(cls, connection: sqlite3.Connection) -> None:
        """Enable WAL, retrying only bounded SQLite lock-contention failures."""
        deadline = time.monotonic() + SQLITE_LOCK_TIMEOUT_SECONDS
        retry_delay = WAL_RETRY_INITIAL_DELAY_SECONDS
        while True:
            lock_error = None
            try:
                current_mode_row = connection.execute("PRAGMA journal_mode").fetchone()
                current_mode = str(current_mode_row[0]).casefold()
                if current_mode == "wal":
                    return

                selected_mode_row = connection.execute("PRAGMA journal_mode = WAL").fetchone()
                selected_mode = str(selected_mode_row[0]).casefold()
                if selected_mode == "wal":
                    return
            except sqlite3.OperationalError as error:
                if not cls._is_sqlite_lock_error(error) or time.monotonic() >= deadline:
                    raise
                lock_error = error
            else:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "SQLite refused to enable WAL mode "
                        f"(selected journal_mode={selected_mode!r})"
                    )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if lock_error is not None:
                    raise lock_error
                raise RuntimeError("SQLite refused to enable WAL mode before timeout")
            time.sleep(min(retry_delay, remaining))
            retry_delay = min(retry_delay * 2, WAL_RETRY_MAX_DELAY_SECONDS)

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            # ``executescript`` may commit implicitly, so migrations must use
            # individual statements.  Acquiring the write lock before schema
            # introspection prevents concurrent processes from both deciding
            # that the same column needs to be added.
            self._enable_write_ahead_log(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._migrate_schema(connection)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        finally:
            connection.close()

        # Consultation data can contain protected health information.  Restrict
        # the local database file to its owner where the platform supports it.
        try:
            os.chmod(self.database_path, 0o600)
        except OSError:
            pass

    def _migrate_schema(self, connection: sqlite3.Connection) -> None:
        """Create or upgrade the schema within the caller's write transaction."""
        connection.execute(
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
                    consultation_date TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """
        )

        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(consultations)").fetchall()
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
        if "consultation_date" not in columns:
            connection.execute("ALTER TABLE consultations ADD COLUMN consultation_date TEXT")
        for column in ("invitation_id", "institution_id", "patient_sno", "reg_sno"):
            if column not in columns:
                connection.execute(f"ALTER TABLE consultations ADD COLUMN {column} TEXT")

        connection.execute(
            """
                CREATE TABLE IF NOT EXISTS consultation_number_sequences (
                    consultation_date TEXT NOT NULL,
                    triage_level TEXT NOT NULL
                        CHECK (triage_level IN ('routine', 'urgent')),
                    next_number INTEGER NOT NULL,
                    PRIMARY KEY (consultation_date, triage_level)
                )
            """
        )

        legacy_rows = connection.execute(
            """
            SELECT id, consultation_date, created_at
            FROM consultations
            WHERE consultation_date IS NULL OR consultation_date = ''
            """
        ).fetchall()
        for row in legacy_rows:
            consultation_date = row["consultation_date"] or self._local_date_for_timestamp(
                row["created_at"]
            )
            connection.execute(
                """
                UPDATE consultations
                SET consultation_date = ?
                WHERE id = ?
                """,
                (consultation_date, row["id"]),
            )

        self._repair_legacy_composite_collisions(connection)
        self._initialize_number_sequences(connection)

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_consultations_type_created_at
                ON consultations (consultation_type, created_at DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_consultations_status_created_at
                ON consultations (workflow_status, created_at DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_consultations_display_created_at
                ON consultations (display_number, created_at DESC)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                idx_consultations_date_registration
                ON consultations (consultation_date, display_number)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS invitations (
                invite_id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL UNIQUE,
                institution_id TEXT NOT NULL,
                patient_sno TEXT NOT NULL,
                reg_sno TEXT NOT NULL,
                prefill_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('active', 'consumed', 'revoked', 'expired')),
                expires_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                consumed_at TEXT,
                consultation_id TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_invitations_encounter_status
            ON invitations (institution_id, reg_sno, status)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS patient_sessions (
                session_id TEXT PRIMARY KEY,
                session_token_hash TEXT NOT NULL UNIQUE,
                invite_id TEXT NOT NULL REFERENCES invitations(invite_id),
                interview_session_id TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                revoked_at TEXT,
                runtime_state_json TEXT,
                runtime_updated_at TEXT
            )
            """
        )
        patient_session_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(patient_sessions)").fetchall()
        }
        if "runtime_state_json" not in patient_session_columns:
            connection.execute("ALTER TABLE patient_sessions ADD COLUMN runtime_state_json TEXT")
        if "runtime_updated_at" not in patient_session_columns:
            connection.execute("ALTER TABLE patient_sessions ADD COLUMN runtime_updated_at TEXT")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_type TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                institution_id TEXT,
                outcome TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_audit_events_created_at
            ON audit_events (created_at)
            """
        )

        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

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

    def _local_date_for_timestamp(self, timestamp: str) -> str:
        try:
            parsed = datetime.fromisoformat(timestamp)
        except (TypeError, ValueError):
            parsed = self._now_provider()
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(self.local_timezone).date().isoformat()

    def _creation_times(self) -> tuple[str, str]:
        now = self._now_provider()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now_utc = now.astimezone(timezone.utc)
        return (
            now_utc.isoformat(timespec="milliseconds"),
            now_utc.astimezone(self.local_timezone).date().isoformat(),
        )

    @classmethod
    def consultation_id(
        cls,
        consultation_date: str,
        registration_number: str,
    ) -> str:
        """Serialize the permanent composite key used by doctor workflows."""
        normalized_date, normalized_number = cls._parse_consultation_id(
            f"{consultation_date}:{registration_number}"
        )
        return f"{normalized_date}:{normalized_number}"

    @classmethod
    def _parse_consultation_id(cls, consultation_id: str) -> tuple[str, str]:
        if not isinstance(consultation_id, str):
            raise ValueError(CONSULTATION_ID_FORMAT_ERROR)
        match = CONSULTATION_ID_PATTERN.fullmatch(consultation_id)
        if match is None:
            raise ValueError(CONSULTATION_ID_FORMAT_ERROR)
        consultation_date, registration_number = match.groups()
        try:
            date.fromisoformat(consultation_date)
        except ValueError as error:
            raise ValueError(CONSULTATION_ID_DATE_ERROR) from error
        return consultation_date, registration_number

    def _repair_legacy_composite_collisions(self, connection: sqlite3.Connection) -> None:
        """Assign deterministic unused numbers when old same-day displays collide."""
        duplicates = connection.execute(
            """
            SELECT consultation_date, display_number
            FROM consultations
            GROUP BY consultation_date, display_number
            HAVING count(*) > 1
            """
        ).fetchall()
        for duplicate in duplicates:
            rows = connection.execute(
                """
                SELECT id, triage_level
                FROM consultations
                WHERE consultation_date = ? AND display_number = ?
                ORDER BY created_at, id
                """,
                (duplicate["consultation_date"], duplicate["display_number"]),
            ).fetchall()
            for row in rows[1:]:
                replacement = self._first_unused_display_number(
                    connection,
                    duplicate["consultation_date"],
                    row["triage_level"],
                )
                connection.execute(
                    "UPDATE consultations SET display_number = ? WHERE id = ?",
                    (replacement, row["id"]),
                )

    @staticmethod
    def _first_unused_display_number(
        connection: sqlite3.Connection,
        consultation_date: str,
        triage_level: str,
    ) -> str:
        start = 0 if triage_level == "urgent" else 10_000
        maximum = 999 if triage_level == "urgent" else 99_999
        rows = connection.execute(
            """
            SELECT CAST(display_number AS INTEGER) AS number
            FROM consultations
            WHERE consultation_date = ? AND triage_level = ?
            """,
            (consultation_date, triage_level),
        ).fetchall()
        used = {row["number"] for row in rows}
        number = next(
            (candidate for candidate in range(start, maximum + 1) if candidate not in used), None
        )
        if number is None:
            raise RuntimeError(f"{consultation_date} 的{triage_level}問診編號已用完")
        return f"{number:03d}" if triage_level == "urgent" else f"{number:05d}"

    @staticmethod
    def _initialize_number_sequences(connection: sqlite3.Connection) -> None:
        groups = connection.execute(
            """
            SELECT
                consultation_date,
                triage_level,
                max(CAST(display_number AS INTEGER)) AS maximum
            FROM consultations
            WHERE display_number GLOB '[0-9]*'
            GROUP BY consultation_date, triage_level
            """
        ).fetchall()
        for group in groups:
            minimum = 0 if group["triage_level"] == "urgent" else 10_000
            next_number = max(minimum, int(group["maximum"]) + 1)
            connection.execute(
                """
                INSERT OR IGNORE INTO consultation_number_sequences (
                    consultation_date,
                    triage_level,
                    next_number
                ) VALUES (?, ?, ?)
                """,
                (
                    group["consultation_date"],
                    group["triage_level"],
                    next_number,
                ),
            )

    @staticmethod
    def _allocate_display_number(
        connection: sqlite3.Connection,
        consultation_date: str,
        triage_level: str,
    ) -> str:
        row = connection.execute(
            """
            SELECT next_number
            FROM consultation_number_sequences
            WHERE consultation_date = ? AND triage_level = ?
            """,
            (consultation_date, triage_level),
        ).fetchone()
        number = row["next_number"] if row else (0 if triage_level == "urgent" else 10_000)
        maximum = 999 if triage_level == "urgent" else 99_999
        if number > maximum:
            raise RuntimeError(f"{consultation_date} 的{triage_level}問診編號已用完")
        connection.execute(
            """
            INSERT INTO consultation_number_sequences (
                consultation_date,
                triage_level,
                next_number
            ) VALUES (?, ?, ?)
            ON CONFLICT(consultation_date, triage_level) DO UPDATE SET
                next_number = excluded.next_number
            """,
            (consultation_date, triage_level, number + 1),
        )
        return f"{number:03d}" if triage_level == "urgent" else f"{number:05d}"

    def create(self, record: dict[str, Any]) -> str:
        """Insert a result and return its patient-facing queue number."""
        return self.create_with_identifiers(record)["queue_number"]

    def create_with_identifiers(self, record: dict[str, Any]) -> dict[str, str]:
        """Insert a result and return its permanent and patient-facing IDs."""
        data_json = self._serialize_data(record.get("data", {}))
        now, consultation_date = self._creation_times()
        triage_level = record.get("triage_level", "routine")
        if triage_level not in {"routine", "urgent"}:
            raise ValueError("triage_level must be routine or urgent")
        for _ in range(64):
            queue_number = self._queue_number()
            try:
                with closing(self._connect()) as connection, connection:
                    connection.execute("BEGIN IMMEDIATE")
                    display_number = self._allocate_display_number(
                        connection,
                        consultation_date,
                        triage_level,
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
                            consultation_date,
                            created_at,
                            updated_at,
                            invitation_id,
                            institution_id,
                            patient_sno,
                            reg_sno
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                            consultation_date,
                            now,
                            now,
                            record.get("invitation_id"),
                            record.get("institution_id"),
                            record.get("patient_sno"),
                            record.get("reg_sno"),
                        ),
                    )
                    invitation_id = record.get("invitation_id")
                    if invitation_id:
                        consultation_id = self.consultation_id(consultation_date, display_number)
                        connection.execute(
                            """
                            UPDATE invitations
                            SET consultation_id = ?
                            WHERE invite_id = ?
                            """,
                            (consultation_id, invitation_id),
                        )
                return {
                    "consultation_id": self.consultation_id(
                        consultation_date,
                        display_number,
                    ),
                    "queue_number": display_number,
                    "consultation_date": consultation_date,
                }
            except sqlite3.IntegrityError as error:
                if "queue_number" not in str(error):
                    raise

        raise RuntimeError("無法產生未使用的問診編號")

    def upsert_fixed(
        self,
        queue_number: str,
        record: dict[str, Any],
    ) -> str:
        """Insert or refresh a fixed record, used only for synthetic fixtures."""
        if len(queue_number) != 5 or not queue_number.isdigit():
            raise ValueError("queue_number must contain exactly five digits")
        data_json = self._serialize_data(record.get("data", {}))
        now, consultation_date = self._creation_times()
        with closing(self._connect()) as connection, connection:
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
                    consultation_date,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    consultation_date,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT consultation_date, display_number
                FROM consultations
                WHERE queue_number = ?
                """,
                (queue_number,),
            ).fetchone()
        return self.consultation_id(row["consultation_date"], row["display_number"])

    def get(
        self,
        consultation_id: str,
        *,
        institution_id: str | None = None,
    ) -> dict[str, Any] | None:
        consultation_date, registration_number = self._parse_consultation_id(consultation_id)
        with closing(self._connect()) as connection, connection:
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
                    consultation_date,
                    created_at,
                    updated_at,
                    invitation_id,
                    institution_id,
                    patient_sno,
                    reg_sno
                FROM consultations
                WHERE consultation_date = ? AND display_number = ?
                  AND (? IS NULL OR institution_id = ?)
                """,
                (consultation_date, registration_number, institution_id, institution_id),
            ).fetchone()

        if row is None:
            return None
        return self._record_from_row(row)

    def get_by_registration_number(
        self,
        registration_number: str,
        *,
        consultation_date: str | None = None,
        institution_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Resolve a patient-facing registration number by date or global uniqueness."""
        normalized = registration_number.strip()
        if consultation_date:
            return self.get(
                self.consultation_id(consultation_date, normalized),
                institution_id=institution_id,
            )
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT consultation_date, display_number
                FROM consultations
                WHERE display_number = ?
                  AND (? IS NULL OR institution_id = ?)
                ORDER BY created_at DESC, id DESC
                LIMIT 2
                """,
                (normalized, institution_id, institution_id),
            ).fetchall()
        if not rows:
            return None
        if len(rows) > 1:
            raise ValueError("此掛號編號跨日期重複，請指定日期或 consultation_id")
        return self.get(
            self.consultation_id(
                rows[0]["consultation_date"],
                rows[0]["display_number"],
            ),
            institution_id=institution_id,
        )

    def _record_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        consultation_id = self.consultation_id(
            row["consultation_date"],
            row["display_number"],
        )
        return {
            "consultation_id": consultation_id,
            "registration_number": row["display_number"],
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
            "consultation_date": row["consultation_date"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "invitation_id": row["invitation_id"],
            "institution_id": row["institution_id"],
            "patient_sno": row["patient_sno"],
            "reg_sno": row["reg_sno"],
        }

    def list_summaries(
        self,
        *,
        search: str = "",
        limit: int = 30,
        offset: int = 0,
        institution_id: str | None = None,
    ) -> dict[str, Any]:
        """Return paginated metadata without exposing reports or full answers."""
        safe_limit = max(1, min(int(limit), 100))
        safe_offset = max(0, int(offset))
        normalized_search = search.strip()[:100]
        clauses: list[str] = []
        params: list[str] = []
        if institution_id:
            clauses.append("institution_id = ?")
            params.append(institution_id)
        if normalized_search:
            pattern = f"%{normalized_search}%"
            clauses.append("""(
                    display_number LIKE ?
                    OR queue_number LIKE ?
                    OR consultation_date LIKE ?
                    OR coalesce(patient_name, '') LIKE ?
                    OR reason LIKE ?
                )""")
            params.extend((pattern, pattern, pattern, pattern, pattern))
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        where_params = tuple(params)

        with closing(self._connect()) as connection, connection:
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
                    consultation_date,
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
                    "consultation_id": self.consultation_id(
                        row["consultation_date"],
                        row["display_number"],
                    ),
                    "registration_number": row["display_number"],
                    "queue_number": row["display_number"],
                    "patient_name": row["patient_name"] or "未提供",
                    "type": row["consultation_type"],
                    "reason": row["reason"],
                    "gender": data.get("gender", "未提供"),
                    "age": data.get("age", "未提供"),
                    "triage_level": row["triage_level"],
                    "workflow_status": row["workflow_status"],
                    "has_structured_note": bool(row["structured_note"]),
                    "consultation_date": row["consultation_date"],
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
        consultation_id: str,
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
        consultation_date, registration_number = self._parse_consultation_id(consultation_id)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE consultations
                SET structured_note = ?,
                    structured_sources_json = ?,
                    structured_note_created_at = ?,
                    updated_at = ?
                WHERE consultation_date = ? AND display_number = ?
                """,
                (
                    normalized_note,
                    sources_json,
                    now,
                    now,
                    consultation_date,
                    registration_number,
                ),
            )
        return cursor.rowcount == 1

    def save_generated_report(
        self,
        consultation_id: str,
        report: str,
    ) -> bool:
        """Persist an AI report generated after the patient got a number."""
        normalized_report = report.strip()
        if not normalized_report:
            raise ValueError("generated report must not be empty")
        now = _utc_now()
        consultation_date, registration_number = self._parse_consultation_id(consultation_id)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE consultations
                SET report = ?,
                    updated_at = ?
                WHERE consultation_date = ? AND display_number = ?
                """,
                (
                    normalized_report,
                    now,
                    consultation_date,
                    registration_number,
                ),
            )
        return cursor.rowcount == 1

    def update_workflow_status(
        self,
        consultation_id: str,
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
        consultation_date, registration_number = self._parse_consultation_id(consultation_id)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE consultations
                SET workflow_status = ?,
                    summary_error = ?,
                    updated_at = ?
                WHERE consultation_date = ? AND display_number = ?
                """,
                (
                    normalized_status,
                    normalized_error,
                    now,
                    consultation_date,
                    registration_number,
                ),
            )
        return cursor.rowcount == 1

    def delete(self, consultation_id: str) -> bool:
        """Permanently delete exactly one date-qualified consultation."""
        consultation_date, registration_number = self._parse_consultation_id(consultation_id)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                DELETE FROM consultations
                WHERE consultation_date = ? AND display_number = ?
                """,
                (consultation_date, registration_number),
            )
        return cursor.rowcount == 1

    def count(self) -> int:
        with closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT count(*) AS total FROM consultations").fetchone()
        return int(row["total"])

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        *,
        actor_type: str,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        institution_id: str | None,
        outcome: str = "success",
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_events (
                actor_type, actor_id, action, resource_type, resource_id,
                institution_id, outcome, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                actor_type,
                actor_id,
                action,
                resource_type,
                resource_id,
                institution_id,
                outcome,
                _utc_now(),
            ),
        )
        cutoff = (datetime.now(timezone.utc) - timedelta(days=AUDIT_RETENTION_DAYS)).isoformat(
            timespec="milliseconds"
        )
        connection.execute("DELETE FROM audit_events WHERE created_at < ?", (cutoff,))
        connection.execute(
            """
            DELETE FROM audit_events
            WHERE id <= COALESCE(
                (
                    SELECT id FROM audit_events
                    ORDER BY id DESC
                    LIMIT 1 OFFSET ?
                ),
                0
            )
            """,
            (AUDIT_MAX_ROWS,),
        )

    def record_audit_event(
        self,
        *,
        actor_type: str,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        institution_id: str | None,
        outcome: str,
    ) -> None:
        """Persist a bounded security event containing identifiers only.

        Callers must use opaque or pseudonymous identifiers.  Free-form request
        data is intentionally unsupported by this API and by the table schema.
        """
        with closing(self._connect()) as connection, connection:
            self._audit(
                connection,
                actor_type=actor_type[:40],
                actor_id=actor_id[:200],
                action=action[:100],
                resource_type=resource_type[:60],
                resource_id=resource_id[:200],
                institution_id=(institution_id[:100] if institution_id else None),
                outcome=outcome[:40],
            )

    def create_invitation(
        self,
        *,
        institution_id: str,
        patient_sno: str,
        reg_sno: str,
        prefill: dict[str, Any],
        actor_sub: str,
        ttl_seconds: int = 24 * 60 * 60,
    ) -> dict[str, str]:
        token = secrets.token_urlsafe(32)
        invite_id = secrets.token_hex(16)
        now = datetime.now(timezone.utc)
        created_at = now.isoformat(timespec="milliseconds")
        expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat(timespec="milliseconds")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE invitations
                SET status = 'revoked'
                WHERE institution_id = ? AND reg_sno = ? AND status = 'active'
                """,
                (institution_id, reg_sno),
            )
            connection.execute(
                """
                INSERT INTO invitations (
                    invite_id, token_hash, institution_id, patient_sno, reg_sno,
                    prefill_json, status, expires_at, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    invite_id,
                    self._token_hash(token),
                    institution_id,
                    patient_sno,
                    reg_sno,
                    self._serialize_data(prefill),
                    expires_at,
                    actor_sub,
                    created_at,
                ),
            )
            self._audit(
                connection,
                actor_type="ucc_user",
                actor_id=actor_sub,
                action="invitation.create",
                resource_type="invitation",
                resource_id=invite_id,
                institution_id=institution_id,
            )
        return {
            "invite_id": invite_id,
            "token": token,
            "expires_at": expires_at,
            "status": "active",
        }

    def exchange_invitation(
        self,
        token: str,
        *,
        session_ttl_seconds: int = 8 * 60 * 60,
    ) -> dict[str, str] | None:
        now = datetime.now(timezone.utc)
        now_text = now.isoformat(timespec="milliseconds")
        rejected_error: ValueError | None = None
        result: dict[str, str] | None = None
        token_fingerprint = f"token:{self._token_hash(token)[:20]}"
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            invitation = connection.execute(
                """
                SELECT * FROM invitations WHERE token_hash = ?
                """,
                (self._token_hash(token),),
            ).fetchone()
            if invitation is None:
                self._audit(
                    connection,
                    actor_type="anonymous",
                    actor_id=token_fingerprint,
                    action="invitation.exchange",
                    resource_type="invitation",
                    resource_id=token_fingerprint,
                    institution_id=None,
                    outcome="denied",
                )
            elif invitation["status"] != "active":
                self._audit(
                    connection,
                    actor_type="anonymous",
                    actor_id=token_fingerprint,
                    action="invitation.exchange",
                    resource_type="invitation",
                    resource_id=invitation["invite_id"],
                    institution_id=invitation["institution_id"],
                    outcome="denied",
                )
                rejected_error = ValueError("Invitation has already been used or revoked")
            elif invitation["expires_at"] <= now_text:
                connection.execute(
                    "UPDATE invitations SET status = 'expired' WHERE invite_id = ?",
                    (invitation["invite_id"],),
                )
                self._audit(
                    connection,
                    actor_type="anonymous",
                    actor_id=token_fingerprint,
                    action="invitation.exchange",
                    resource_type="invitation",
                    resource_id=invitation["invite_id"],
                    institution_id=invitation["institution_id"],
                    outcome="denied",
                )
            else:
                session_token = secrets.token_urlsafe(48)
                session_id = secrets.token_hex(16)
                interview_session_id = f"patient-{secrets.token_hex(16)}"
                expires_at = (now + timedelta(seconds=session_ttl_seconds)).isoformat(
                    timespec="milliseconds"
                )
                connection.execute(
                    """
                    UPDATE invitations
                    SET status = 'consumed', consumed_at = ?
                    WHERE invite_id = ? AND status = 'active'
                    """,
                    (now_text, invitation["invite_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO patient_sessions (
                        session_id, session_token_hash, invite_id, interview_session_id,
                        expires_at, created_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        self._token_hash(session_token),
                        invitation["invite_id"],
                        interview_session_id,
                        expires_at,
                        now_text,
                        now_text,
                    ),
                )
                self._audit(
                    connection,
                    actor_type="patient",
                    actor_id=session_id,
                    action="invitation.exchange",
                    resource_type="invitation",
                    resource_id=invitation["invite_id"],
                    institution_id=invitation["institution_id"],
                )
                result = {"session_token": session_token, "expires_at": expires_at}
        if rejected_error is not None:
            raise rejected_error
        return result

    def get_patient_session(self, session_token: str) -> dict[str, Any] | None:
        now = _utc_now()
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT
                    ps.session_id, ps.interview_session_id, ps.expires_at,
                    i.invite_id, i.institution_id, i.patient_sno, i.reg_sno,
                    i.prefill_json, i.consultation_id
                FROM patient_sessions ps
                JOIN invitations i ON i.invite_id = ps.invite_id
                WHERE ps.session_token_hash = ?
                  AND ps.revoked_at IS NULL
                  AND ps.expires_at > ?
                """,
                (self._token_hash(session_token), now),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE patient_sessions SET last_seen_at = ? WHERE session_id = ?",
                (now, row["session_id"]),
            )
        return {
            "session_id": row["session_id"],
            "interview_session_id": row["interview_session_id"],
            "expires_at": row["expires_at"],
            "invite_id": row["invite_id"],
            "institution_id": row["institution_id"],
            "patient_sno": row["patient_sno"],
            "reg_sno": row["reg_sno"],
            "prefill": json.loads(row["prefill_json"]),
            "consultation_id": row["consultation_id"],
        }

    @staticmethod
    def _serialize_patient_runtime_state(state: dict[str, Any]) -> str:
        """Serialize bounded, non-executable patient interview state."""
        if not isinstance(state, dict):
            raise ValueError("patient runtime state must be a JSON object")
        try:
            serialized = json.dumps(
                state,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError, RecursionError) as error:
            raise ValueError("patient runtime state must contain only JSON values") from error
        if len(serialized.encode("utf-8")) > MAX_PATIENT_RUNTIME_STATE_BYTES:
            raise ValueError("patient runtime state exceeds the storage limit")
        return serialized

    def save_patient_runtime_state(
        self,
        *,
        patient_session_id: str,
        interview_session_id: str,
        institution_id: str,
        patient_sno: str,
        state: dict[str, Any],
    ) -> bool:
        """Persist one interview only when every patient binding still matches."""
        if state.get("session_id") != interview_session_id:
            raise ValueError("patient runtime state belongs to another interview")
        serialized = self._serialize_patient_runtime_state(state)
        now = _utc_now()
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE patient_sessions
                SET runtime_state_json = ?, runtime_updated_at = ?, last_seen_at = ?
                WHERE session_id = ?
                  AND interview_session_id = ?
                  AND revoked_at IS NULL
                  AND expires_at > ?
                  AND EXISTS (
                      SELECT 1
                      FROM invitations i
                      WHERE i.invite_id = patient_sessions.invite_id
                        AND i.institution_id = ?
                        AND i.patient_sno = ?
                  )
                """,
                (
                    serialized,
                    now,
                    now,
                    patient_session_id,
                    interview_session_id,
                    now,
                    institution_id,
                    patient_sno,
                ),
            )
            return cursor.rowcount == 1

    def load_patient_runtime_state(
        self,
        *,
        patient_session_id: str,
        interview_session_id: str,
        institution_id: str,
        patient_sno: str,
    ) -> dict[str, Any] | None:
        """Restore bounded JSON state for the exact active patient session."""
        now = _utc_now()
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT ps.runtime_state_json
                FROM patient_sessions ps
                JOIN invitations i ON i.invite_id = ps.invite_id
                WHERE ps.session_id = ?
                  AND ps.interview_session_id = ?
                  AND ps.revoked_at IS NULL
                  AND ps.expires_at > ?
                  AND i.institution_id = ?
                  AND i.patient_sno = ?
                """,
                (
                    patient_session_id,
                    interview_session_id,
                    now,
                    institution_id,
                    patient_sno,
                ),
            ).fetchone()
        if row is None or not row["runtime_state_json"]:
            return None
        raw = row["runtime_state_json"]
        if len(raw.encode("utf-8")) > MAX_PATIENT_RUNTIME_STATE_BYTES:
            return None
        try:
            state = json.loads(raw)
        except (TypeError, json.JSONDecodeError, RecursionError):
            return None
        if not isinstance(state, dict) or state.get("session_id") != interview_session_id:
            return None
        return state
