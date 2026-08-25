from __future__ import annotations

import gc
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("GROQ_API_KEY", "test-only-not-a-real-key")

from fastapi import HTTPException
from starlette.requests import Request

from app.routes import doctor, invitations
from app.security import UccPrincipal, _ucc_principal_context
from app.services.security_audit import audit_event, opaque_id, safe_log
from infrastructure.consultation_repository import ConsultationRepository


class SecurityAuditLoggingTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "audit.db"
        self.repository = ConsultationRepository(self.database_path)

    def tearDown(self):
        gc.collect()
        self.temporary_directory.cleanup()

    def _audit_rows(self):
        with closing(sqlite3.connect(self.database_path)) as connection:
            return connection.execute(
                """
                SELECT actor_type, actor_id, action, resource_type,
                       resource_id, institution_id, outcome
                FROM audit_events ORDER BY id
                """
            ).fetchall()

    def test_failed_invitation_exchange_is_audited_without_token_or_prefill(self):
        token = "raw-token-Alice-Sensitive"
        self.assertIsNone(self.repository.exchange_invitation(token))

        expired = self.repository.create_invitation(
            institution_id="hospital-a",
            patient_sno="patient-a",
            reg_sno="registration-a",
            prefill={"name": "Alice Sensitive"},
            actor_sub="doctor-1",
            ttl_seconds=-1,
        )
        self.assertIsNone(self.repository.exchange_invitation(expired["token"]))

        active = self.repository.create_invitation(
            institution_id="hospital-a",
            patient_sno="patient-a",
            reg_sno="registration-b",
            prefill={"name": "Alice Sensitive"},
            actor_sub="doctor-1",
        )
        self.assertIsNotNone(self.repository.exchange_invitation(active["token"]))
        with self.assertRaises(ValueError):
            self.repository.exchange_invitation(active["token"])

        rows = self._audit_rows()
        denied = [row for row in rows if row[2] == "invitation.exchange" and row[6] == "denied"]
        self.assertEqual(len(denied), 3)
        serialized = repr(rows)
        for secret in (token, expired["token"], active["token"], "Alice Sensitive"):
            self.assertNotIn(secret, serialized)

    def test_integration_route_events_use_pseudonymous_resources(self):
        principal = UccPrincipal(
            "doctor-1",
            "hospital-a",
            frozenset({"consultation:read"}),
            {},
        )
        request = Request({"type": "http", "method": "GET", "path": "/v1/patient/session"})
        request.state.patient_session = {
            "session_id": "patient-session-secret",
            "institution_id": "hospital-a",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "interview_session_id": "interview-secret",
            "consultation_id": None,
        }

        with patch("app.runtime.consultation_repository", self.repository):
            context_token = _ucc_principal_context.set(principal)
            try:
                doctor.list_consultations(search="", limit=30, offset=0)
            finally:
                _ucc_principal_context.reset(context_token)
            invitations.patient_session(request, request.state.patient_session)
            audit_event(
                "patient.chat",
                "success",
                actor_type="patient",
                actor_id=opaque_id("patient_session", "patient-session-secret"),
                institution_id="hospital-a",
                resource_type="patient_session",
                resource_id=opaque_id("patient_session", "patient-session-secret"),
            )

        rows = self._audit_rows()
        actions = {row[2] for row in rows}
        self.assertTrue(
            {"doctor.consultation.list", "patient.session.restore", "patient.chat"} <= actions
        )
        serialized = repr(rows)
        self.assertNotIn("patient-session-secret", serialized)
        self.assertNotIn("interview-secret", serialized)

    def test_doctor_delete_is_audited_without_consultation_or_patient_identifiers(self):
        consultation = self.repository.create_with_identifiers(
            {
                "type": "headache",
                "summary": "summary-without-pii",
                "report": "report-without-pii",
                "data": {"name": "Alice Delete Sensitive"},
                "institution_id": "hospital-a",
                "patient_sno": "patient-delete-sensitive",
                "reg_sno": "registration-delete-sensitive",
            }
        )
        consultation_id = consultation["consultation_id"]
        principal = UccPrincipal(
            "doctor-1",
            "hospital-a",
            frozenset({"consultation:read", "consultation:delete"}),
            {},
        )

        with patch("app.runtime.consultation_repository", self.repository):
            context_token = _ucc_principal_context.set(principal)
            try:
                response = doctor.delete_consultation(consultation_id)
            finally:
                _ucc_principal_context.reset(context_token)

        self.assertEqual(response["status"], "deleted")
        rows = self._audit_rows()
        delete_rows = [row for row in rows if row[2] == "doctor.consultation.delete"]
        self.assertEqual(len(delete_rows), 1)
        self.assertEqual(delete_rows[0][3], "consultation")
        self.assertEqual(delete_rows[0][4], opaque_id("consultation", consultation_id))
        self.assertEqual(delete_rows[0][5], "hospital-a")
        self.assertEqual(delete_rows[0][6], "success")
        serialized = repr(rows)
        for identifier in (
            consultation_id,
            "Alice Delete Sensitive",
            "patient-delete-sensitive",
            "registration-delete-sensitive",
        ):
            self.assertNotIn(identifier, serialized)

    def test_doctor_delete_not_found_uses_generic_pseudonymous_audit(self):
        consultation_id = "2026-08-06:99999"
        principal = UccPrincipal(
            "doctor-1",
            "hospital-a",
            frozenset({"consultation:read", "consultation:delete"}),
            {},
        )

        with patch("app.runtime.consultation_repository", self.repository):
            context_token = _ucc_principal_context.set(principal)
            try:
                with self.assertRaises(HTTPException) as denied:
                    doctor.delete_consultation(consultation_id)
            finally:
                _ucc_principal_context.reset(context_token)

        self.assertEqual(denied.exception.status_code, 404)
        rows = self._audit_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "doctor.consultation.delete")
        self.assertEqual(rows[0][4], opaque_id("consultation", consultation_id))
        self.assertEqual(rows[0][6], "denied")
        self.assertNotIn(consultation_id, repr(rows))

    def test_safe_log_never_emits_exception_message(self):
        secret = "raw-token-and-patient-name-Alice"
        with self.assertLogs("medical_consultation.security", level="WARNING") as captured:
            safe_log(
                "patient.chat",
                "failure",
                error=RuntimeError(secret),
                failure_stage="Must Not Miss",
            )
        output = "\n".join(captured.output)
        self.assertIn("RuntimeError", output)
        self.assertIn("failure_stage=must_not_miss", output)
        self.assertNotIn(secret, output)


if __name__ == "__main__":
    unittest.main()
