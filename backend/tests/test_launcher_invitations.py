from __future__ import annotations

import asyncio
import gc
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException, Response
from pydantic import ValidationError
from starlette.requests import Request

from app.models import ChatRequest, LauncherInvitationCreateRequest
from app.routes import invitations, patient
from app.security import UccPrincipal
from infrastructure.consultation_repository import SCHEMA_VERSION, ConsultationRepository


def _local_principal() -> UccPrincipal:
    return UccPrincipal(
        subject="local-developer",
        institution_id="local-development",
        scopes=frozenset({"consultation:read", "invite:create"}),
        claims={"local_auth_bypass": True, "legacy_frontend_bypass": True},
    )


class _RecordingInvitationRepository:
    def __init__(self):
        self.calls: list[dict] = []

    def create_invitation(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "invite_id": "invite-1",
            "token": "one-time-opaque-code",
            "expires_at": "2099-01-01T00:05:00+00:00",
            "status": "active",
        }


class LauncherInvitationRouteTests(unittest.TestCase):
    def setUp(self):
        self.payload = LauncherInvitationCreateRequest.model_validate(
            {
                "issuer": "https://fhir.example.test/base/",
                "patient_id": "synthetic-patient-1",
                "encounter_id": "synthetic-encounter-1",
                "prefill": {
                    "name": "Synthetic Patient",
                    "gender": "男性",
                    "clinical_codings": [
                        {
                            "field": "chronic",
                            "system": "http://snomed.info/sct",
                            "code": "38341003",
                            "display": "Hypertensive disorder",
                        }
                    ],
                },
            }
        )

    def test_launcher_is_fail_closed_and_rejects_non_local_principals(self):
        with patch.dict(os.environ, {"LOCAL_FHIR_LAUNCHER_ENABLED": "false"}):
            with self.assertRaises(HTTPException) as disabled:
                invitations.require_local_fhir_launcher(principal=_local_principal())
        self.assertEqual(disabled.exception.status_code, 403)

        formal_principal = UccPrincipal(
            subject="doctor-1",
            institution_id="hospital-a",
            scopes=frozenset({"consultation:read", "invite:create"}),
            claims={"token_use": "doctor"},
        )
        with patch.dict(os.environ, {"LOCAL_FHIR_LAUNCHER_ENABLED": "true"}):
            with self.assertRaises(HTTPException) as formal:
                invitations.require_local_fhir_launcher(principal=formal_principal)
            allowed = invitations.require_local_fhir_launcher(principal=_local_principal())
        self.assertEqual(formal.exception.status_code, 403)
        self.assertEqual(allowed.subject, "local-developer")

    def test_ttl_defaults_and_clamps_to_safe_bounds(self):
        cases = {
            "": 300,
            "invalid": 300,
            "-20": 60,
            "59": 60,
            "600": 600,
            "999999": 3600,
        }
        for configured, expected in cases.items():
            with (
                self.subTest(configured=configured),
                patch.dict(
                    os.environ,
                    {"LOCAL_FHIR_LAUNCH_CODE_TTL_SECONDS": configured},
                ),
            ):
                self.assertEqual(invitations._launcher_code_ttl_seconds(), expected)

    def test_launcher_uses_server_owned_binding_and_returns_uncached_raw_code(self):
        repository = _RecordingInvitationRepository()
        response = Response()
        env = {
            "LOCAL_FHIR_LAUNCHER_ENABLED": "true",
            "LOCAL_FHIR_LAUNCH_CODE_TTL_SECONDS": "300",
            "FHIR_PUBLIC_ISSUER": "https://fhir.example.test/base/",
        }
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(invitations.runtime, "consultation_repository", repository),
        ):
            principal = invitations.require_local_fhir_launcher(principal=_local_principal())
            result = invitations.create_launcher_invitation(
                self.payload,
                response,
                principal=principal,
            )

        self.assertEqual(result["code"], "one-time-opaque-code")
        self.assertNotIn("public_url", result)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(len(repository.calls), 1)
        call = repository.calls[0]
        self.assertEqual(call["institution_id"], "local-development")
        self.assertEqual(call["patient_sno"], "synthetic-patient-1")
        self.assertEqual(call["reg_sno"], "synthetic-encounter-1")
        self.assertEqual(call["ttl_seconds"], 300)
        self.assertEqual(
            call["fhir_context"],
            {
                "issuer": "https://fhir.example.test/base",
                "patient_id": "synthetic-patient-1",
                "encounter_id": "synthetic-encounter-1",
            },
        )
        self.assertEqual(call["prefill"]["name"], "Synthetic Patient")

    def test_launcher_rejects_smart_issuer_mismatch(self):
        with patch.dict(
            os.environ,
            {"FHIR_PUBLIC_ISSUER": "https://different-fhir.example.test/base"},
            clear=False,
        ):
            with self.assertRaises(HTTPException) as raised:
                invitations.create_launcher_invitation(
                    self.payload,
                    Response(),
                    principal=_local_principal(),
                )
        self.assertEqual(raised.exception.status_code, 409)

    def test_launcher_requires_server_configured_issuer(self):
        with patch.dict(
            os.environ,
            {"FHIR_PUBLIC_ISSUER": ""},
            clear=False,
        ):
            with self.assertRaises(HTTPException) as raised:
                invitations.create_launcher_invitation(
                    self.payload,
                    Response(),
                    principal=_local_principal(),
                )
        self.assertEqual(raised.exception.status_code, 503)

    def test_request_cannot_override_server_owned_institution(self):
        with self.assertRaises(ValidationError):
            LauncherInvitationCreateRequest.model_validate(
                {
                    "issuer": "https://attacker.example/fhir",
                    "patient_id": "synthetic-patient-1",
                    "prefill": {"name": "Synthetic Patient"},
                    "institution_id": "attacker-hospital",
                }
            )

    def test_request_rejects_unsafe_fhir_issuer(self):
        for issuer in (
            "javascript:alert(1)",
            "https://user:password@fhir.example.test/base",
            "https://fhir.example.test/base?patient=other",
        ):
            with self.subTest(issuer=issuer), self.assertRaises(ValidationError):
                LauncherInvitationCreateRequest.model_validate(
                    {
                        "issuer": issuer,
                        "patient_id": "synthetic-patient-1",
                        "prefill": {"name": "Synthetic Patient"},
                    }
                )

    def test_prefill_rejects_unbounded_clinical_codings(self):
        coding = {
            "field": "chronic",
            "system": "http://snomed.info/sct",
            "code": "38341003",
        }
        with self.assertRaises(ValidationError):
            LauncherInvitationCreateRequest.model_validate(
                {
                    "issuer": "https://fhir.example.test/base",
                    "patient_id": "synthetic-patient-1",
                    "prefill": {"clinical_codings": [coding] * 201},
                }
            )


class LauncherInvitationPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "launcher.db"
        self.repository = ConsultationRepository(self.database_path)

    def tearDown(self):
        del self.repository
        gc.collect()
        self.temp_directory.cleanup()

    def _create_and_exchange(self):
        invitation = self.repository.create_invitation(
            institution_id="local-development",
            patient_sno="synthetic-patient-1",
            reg_sno="synthetic-encounter-1",
            prefill={"name": "Trusted Synthetic Patient", "gender": "女性"},
            actor_sub="local-developer",
            ttl_seconds=300,
            fhir_context={
                "issuer": "https://fhir.example.test/base",
                "patient_id": "synthetic-patient-1",
                "encounter_id": "synthetic-encounter-1",
            },
        )
        exchange = self.repository.exchange_invitation(invitation["token"])
        return invitation, exchange

    def test_schema_raw_code_hashing_single_use_and_context_restoration(self):
        invitation, exchange = self._create_and_exchange()
        with self.assertRaisesRegex(ValueError, "used or revoked"):
            self.repository.exchange_invitation(invitation["token"])

        restored = self.repository.get_patient_session(exchange["session_token"])
        self.assertEqual(
            restored["fhir_context"],
            {
                "issuer": "https://fhir.example.test/base",
                "patient_id": "synthetic-patient-1",
                "encounter_id": "synthetic-encounter-1",
            },
        )
        request = Request({"type": "http", "method": "GET", "path": "/v1/patient/session"})
        request.state.patient_session = restored
        with patch.object(
            invitations.runtime,
            "consultation_repository",
            self.repository,
        ):
            session_response = invitations.patient_session(request, restored)
        self.assertEqual(session_response["patient_name"], "Trusted Synthetic Patient")
        self.assertEqual(session_response["fhir_patient_id"], "synthetic-patient-1")
        self.assertEqual(
            session_response["fhir_encounter_id"],
            "synthetic-encounter-1",
        )
        with closing(sqlite3.connect(self.database_path)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            columns = {row[1] for row in connection.execute("PRAGMA table_info(invitations)")}
            stored = connection.execute(
                "SELECT token_hash, prefill_json, fhir_issuer, "
                "fhir_patient_id, fhir_encounter_id FROM invitations"
            ).fetchone()
            session_hash = connection.execute(
                "SELECT session_token_hash FROM patient_sessions"
            ).fetchone()[0]

        self.assertEqual(version, SCHEMA_VERSION, 11)
        self.assertTrue({"fhir_issuer", "fhir_patient_id", "fhir_encounter_id"} <= columns)
        serialized_storage = repr((stored, session_hash))
        self.assertNotIn(invitation["token"], serialized_storage)
        self.assertNotIn(exchange["session_token"], serialized_storage)

    def test_server_context_enters_initial_interview_and_client_cannot_replace_it(self):
        _, exchange = self._create_and_exchange()
        bound = self.repository.get_patient_session(exchange["session_token"])
        isolated_sessions = {}

        with (
            patch.object(patient, "INTERVIEW_ENGINE", "questionnaire"),
            patch.object(patient, "sessions", isolated_sessions),
            patch.object(patient, "consultation_repository", self.repository),
            patch.object(patient, "current_patient_session", return_value=bound),
        ):
            started = asyncio.run(
                patient.chat(
                    ChatRequest(
                        session_id="attacker-session",
                        patient_prefill={"name": "Attacker"},
                    ),
                    BackgroundTasks(),
                )
            )
            with self.assertRaises(HTTPException) as tampered:
                asyncio.run(
                    patient.chat(
                        ChatRequest(
                            session_id="attacker-session",
                            fhir_context={
                                "patient_id": "other-patient",
                                "source": "direct",
                            },
                        ),
                        BackgroundTasks(),
                    )
                )

        self.assertEqual(tampered.exception.status_code, 403)
        self.assertEqual(started["session_id"], bound["interview_session_id"])
        state = isolated_sessions[bound["interview_session_id"]]
        self.assertEqual(state["data"]["name"], "Trusted Synthetic Patient")
        self.assertEqual(state["fhir_context"], bound["fhir_context"])

        created = self.repository.create_with_identifiers(
            {
                "type": "other",
                "summary": "Synthetic summary",
                "report": "Synthetic report",
                "data": state["data"],
                **patient._record_integration_metadata(state),
            }
        )
        stored = self.repository.get(
            created["consultation_id"],
            institution_id="local-development",
        )
        self.assertEqual(stored["fhir_context"], bound["fhir_context"])


if __name__ == "__main__":
    unittest.main()
