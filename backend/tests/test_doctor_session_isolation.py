import asyncio
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.models import DoctorChatRequest, LoadPatientRequest
from app.routes import doctor
from app.security import UccPrincipal


def _principal(institution: str, subject: str) -> UccPrincipal:
    return UccPrincipal(
        subject=subject,
        institution_id=institution,
        scopes=frozenset({"consultation:read", "consultation:chat"}),
        claims={},
    )


class _AccessibleConsultationRepository:
    """A tenant-scoped record stub; load must fail at owner binding, not lookup."""

    def get(self, consultation_id: str, *, institution_id: str):
        return {
            "consultation_id": consultation_id,
            "institution_id": institution_id,
        }


class DoctorSessionIsolationTests(unittest.TestCase):
    def setUp(self):
        self.sessions = {}
        self.owner = _principal("hospital-a", "doctor-a")
        self.other_doctor = _principal("hospital-a", "doctor-b")
        self.other_institution = _principal("hospital-b", "doctor-a")

    def _create_for_owner(self, session_id: str = "shared-session"):
        with patch.object(doctor.runtime, "doctor_sessions", self.sessions), patch.object(
            doctor, "current_ucc_principal", return_value=self.owner
        ):
            key, session = doctor._doctor_session(session_id, create=True)
            session["patient"] = {"consultation_id": "case-a", "queue_number": "10001"}
            session["history"] = [{"user": "private", "assistant": "private"}]
        return key, session

    def _assert_hidden_from(self, principal: UccPrincipal):
        original_key, original_session = self._create_for_owner()
        snapshot = {
            "patient": dict(original_session["patient"]),
            "history": list(original_session["history"]),
        }

        with patch.object(doctor.runtime, "doctor_sessions", self.sessions), patch.object(
            doctor, "current_ucc_principal", return_value=principal
        ), patch.object(
            doctor.runtime,
            "consultation_repository",
            _AccessibleConsultationRepository(),
        ):
            for operation in (
                lambda: doctor.load_patient(
                    LoadPatientRequest(
                        session_id="shared-session",
                        consultation_id="2026-08-06:10001",
                    )
                ),
                lambda: doctor.unload_patient("shared-session"),
                lambda: doctor.doctor_reset("shared-session"),
                lambda: asyncio.run(
                    doctor.doctor_chat(
                        DoctorChatRequest(
                            session_id="shared-session",
                            message="show private state",
                        )
                    )
                ),
            ):
                with self.subTest(operation=operation), self.assertRaises(HTTPException) as raised:
                    operation()
                self.assertEqual(raised.exception.status_code, 404)
                self.assertEqual(raised.exception.detail, "Physician session not found")

            with self.assertRaises(HTTPException) as raised:
                doctor._doctor_session("shared-session", create=True)
            self.assertEqual(raised.exception.status_code, 404)

        self.assertEqual(set(self.sessions), {original_key})
        self.assertEqual(original_session["patient"], snapshot["patient"])
        self.assertEqual(original_session["history"], snapshot["history"])

    def test_same_session_id_is_hidden_from_other_doctor(self):
        self._assert_hidden_from(self.other_doctor)

    def test_same_session_id_is_hidden_from_other_institution(self):
        self._assert_hidden_from(self.other_institution)

    def test_owner_can_unload_and_reset_only_own_session(self):
        key, _ = self._create_for_owner()
        with patch.object(doctor.runtime, "doctor_sessions", self.sessions), patch.object(
            doctor, "current_ucc_principal", return_value=self.owner
        ):
            self.assertEqual(doctor.unload_patient("shared-session"), {"status": "ok"})
            self.assertIsNone(self.sessions[key]["patient"])
            self.assertEqual(self.sessions[key]["history"], [])
            self.assertEqual(
                doctor.doctor_reset("shared-session"),
                {"status": "ok", "cleared": "shared-session"},
            )
        self.assertEqual(self.sessions, {})

    def test_missing_session_uses_same_not_found_response(self):
        with patch.object(doctor.runtime, "doctor_sessions", self.sessions), patch.object(
            doctor, "current_ucc_principal", return_value=self.other_doctor
        ):
            for operation in (
                lambda: doctor.unload_patient("missing"),
                lambda: doctor.doctor_reset("missing"),
                lambda: asyncio.run(
                    doctor.doctor_chat(
                        DoctorChatRequest(session_id="missing", message="hello")
                    )
                ),
            ):
                with self.assertRaises(HTTPException) as raised:
                    operation()
                self.assertEqual(raised.exception.status_code, 404)
                self.assertEqual(raised.exception.detail, "Physician session not found")

    def test_cleanup_preserves_composite_key_ownership(self):
        owner_key, _ = self._create_for_owner("expired")
        live_key = ("hospital-b", "doctor-b", "live")
        self.sessions[owner_key]["ts"] = 0
        self.sessions[live_key] = {
            "history": [],
            "patient": None,
            "ts": time.time(),
            "institution_id": "hospital-b",
            "doctor_sub": "doctor-b",
        }
        with patch.object(doctor.runtime, "doctor_sessions", self.sessions):
            doctor._cleanup_sessions()
        self.assertNotIn(owner_key, self.sessions)
        self.assertIn(live_key, self.sessions)


if __name__ == "__main__":
    unittest.main()
