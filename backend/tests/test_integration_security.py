import asyncio
import gc
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from app.models import InvitationCreateRequest, InvitationPrefill
from app.routes import doctor
from app.security import (
    _claim_scopes,
    authenticate_ucc,
    current_patient_session,
    require_patient_session,
)
from infrastructure.consultation_repository import ConsultationRepository


class IntegrationSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.repository = ConsultationRepository(
            Path(self.temp_directory.name) / "integration.db"
        )

    def tearDown(self):
        del self.repository
        gc.collect()
        self.temp_directory.cleanup()

    def test_scope_claim_forms_are_merged(self):
        scopes = _claim_scopes(
            {
                "scope": "consultation:read invite:create",
                "scopes": ["rules:read", "invite:create"],
            }
        )
        self.assertEqual(
            scopes,
            {"consultation:read", "invite:create", "rules:read"},
        )

    @staticmethod
    def _request(client_host: str) -> Request:
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/v1/chat",
                "headers": [],
                "client": (client_host, 12345),
                "server": ("127.0.0.1", 8000),
                "scheme": "http",
                "query_string": b"",
            }
        )

    async def _resolve_patient_dependency(
        self,
        client_host: str,
        session_token: str | None = None,
    ):
        dependency = require_patient_session(
            self._request(client_host),
            session_token,
        )
        try:
            return await anext(dependency)
        finally:
            await dependency.aclose()

    def test_local_auth_bypass_only_allows_loopback(self):
        with patch.dict(os.environ, {"ALLOW_LOCAL_AUTH_BYPASS": "true"}):
            self.assertIsNone(
                asyncio.run(self._resolve_patient_dependency("127.0.0.1"))
            )

            with self.assertRaises(HTTPException) as denied:
                asyncio.run(self._resolve_patient_dependency("192.168.1.20"))
            self.assertEqual(denied.exception.status_code, 401)
            self.assertEqual(denied.exception.detail, "Patient session required")

            principal = authenticate_ucc(self._request("127.23.45.67"), None)
            self.assertEqual(principal.subject, "local-developer")
            self.assertIn("consultation:read", principal.scopes)
            self.assertTrue(principal.claims["legacy_frontend_bypass"])
            self.assertIsNone(doctor._consultation_institution_scope(principal))
            with self.assertRaises(HTTPException) as remote_bearer:
                authenticate_ucc(self._request("192.168.1.20"), None)
            self.assertEqual(remote_bearer.exception.detail, "Bearer token required")

        with patch.dict(
            os.environ,
            {
                "ALLOW_LOCAL_AUTH_BYPASS": "false",
                "ALLOW_LOCAL_ANONYMOUS_PATIENT": "false",
            },
        ):
            with self.assertRaises(HTTPException) as disabled:
                asyncio.run(self._resolve_patient_dependency("127.0.0.1"))
            self.assertEqual(disabled.exception.status_code, 401)
            with self.assertRaises(HTTPException) as bearer_required:
                authenticate_ucc(self._request("127.0.0.1"), None)
            self.assertEqual(bearer_required.exception.detail, "Bearer token required")

    def test_only_legacy_frontend_bypass_can_read_across_institutions(self):
        formal_principal = doctor.UccPrincipal(
            subject="doctor-1",
            institution_id="hospital-a",
            scopes=frozenset({"consultation:read"}),
            claims={},
        )
        self.assertEqual(
            doctor._consultation_institution_scope(formal_principal),
            "hospital-a",
        )

        local_principal = doctor.UccPrincipal(
            subject="local-developer",
            institution_id="local-development",
            scopes=frozenset({"consultation:read"}),
            claims={"legacy_frontend_bypass": True},
        )
        with patch.object(
            doctor, "current_ucc_principal", return_value=local_principal
        ), patch.object(
            doctor.runtime.consultation_repository,
            "list_summaries",
            return_value={"items": [], "total": 0, "limit": 30, "offset": 0},
        ) as list_summaries:
            doctor.list_consultations(search="", limit=30, offset=0)

        list_summaries.assert_called_once_with(
            search="",
            limit=30,
            offset=0,
            institution_id=None,
        )

    def test_authenticated_patient_context_is_reset_in_the_same_async_context(self):
        from app import runtime

        session = {"session_token": "opaque", "interview_session_id": "interview-1"}
        with patch.object(
            runtime.consultation_repository,
            "get_patient_session",
            return_value=session,
        ):
            resolved = asyncio.run(
                self._resolve_patient_dependency("192.168.1.20", "opaque")
            )

        self.assertEqual(resolved, session)
        self.assertIsNone(current_patient_session())

    def test_loopback_chat_dependency_completes_without_contextvar_thread_error(self):
        async def request_chat():
            import httpx

            from app.factory import app

            transport = httpx.ASGITransport(
                app=app,
                client=("127.0.0.1", 45678),
            )
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8000",
            ) as client:
                return await client.post(
                    "/v1/chat",
                    json={"message": "", "session_id": "loopback-context-test"},
                )

        with patch.dict(os.environ, {"ALLOW_LOCAL_AUTH_BYPASS": "true"}):
            response = asyncio.run(request_chat())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], "loopback-context-test")

    def test_ucc_prefill_is_normalized_for_existing_patient_workflow(self):
        prefill = InvitationPrefill(
            name="Test Patient",
            allergies="penicillin",
            current_medications="aspirin",
            medical_history="hypertension",
            surgical_history="appendectomy",
        ).as_patient_prefill()
        self.assertEqual(prefill["allergy"], "penicillin")
        self.assertEqual(prefill["current_meds"], "aspirin")
        self.assertEqual(prefill["chronic"], "hypertension")
        self.assertEqual(prefill["surgery"], "appendectomy")

    def test_ucc_integer_references_and_history_lists_are_normalized(self):
        request = InvitationCreateRequest.model_validate(
            {
                "institution_id": " hospital-a ",
                "patient_sno": 10,
                "reg_sno": 20,
                "prefill": {
                    "allergies": [" penicillin ", "latex"],
                    "current_medications": ["aspirin"],
                    "medical_history": ["hypertension"],
                    "surgical_history": ["appendectomy"],
                },
            }
        )

        self.assertEqual(request.institution_id, "hospital-a")
        self.assertEqual(request.patient_sno, "10")
        self.assertEqual(request.reg_sno, "20")
        self.assertEqual(request.prefill.allergies, "penicillin; latex")
        self.assertEqual(
            request.prefill.as_patient_prefill()["current_meds"],
            "aspirin",
        )

    def test_ucc_contract_rejects_unsafe_reference_and_history_values(self):
        invalid_references = (True, 1.25, {"value": "1"}, ["1"])
        for value in invalid_references:
            with self.subTest(reference=value), self.assertRaises(ValidationError):
                InvitationCreateRequest.model_validate(
                    {
                        "institution_id": "hospital-a",
                        "patient_sno": value,
                        "reg_sno": "visit-1",
                    }
                )

        invalid_history = (True, 7, {"value": "penicillin"}, ["penicillin", 7])
        for value in invalid_history:
            with self.subTest(history=value), self.assertRaises(ValidationError):
                InvitationCreateRequest.model_validate(
                    {
                        "institution_id": "hospital-a",
                        "patient_sno": "patient-1",
                        "reg_sno": "visit-1",
                        "prefill": {"allergies": value},
                    }
                )

    def test_invitation_is_single_use_and_recreation_revokes_previous_token(self):
        old = self.repository.create_invitation(
            institution_id="hospital-a",
            patient_sno="patient-1",
            reg_sno="visit-1",
            prefill={"name": "Test Patient"},
            actor_sub="doctor-1",
        )
        replacement = self.repository.create_invitation(
            institution_id="hospital-a",
            patient_sno="patient-1",
            reg_sno="visit-1",
            prefill={"name": "Test Patient"},
            actor_sub="doctor-1",
        )

        with self.assertRaisesRegex(ValueError, "used or revoked"):
            self.repository.exchange_invitation(old["token"])
        exchanged = self.repository.exchange_invitation(replacement["token"])
        with self.assertRaisesRegex(ValueError, "used or revoked"):
            self.repository.exchange_invitation(replacement["token"])

        session = self.repository.get_patient_session(exchanged["session_token"])
        self.assertEqual(session["institution_id"], "hospital-a")
        self.assertEqual(session["reg_sno"], "visit-1")
        self.assertEqual(session["prefill"]["name"], "Test Patient")

    def test_consultations_are_linked_and_filtered_by_institution(self):
        invitation = self.repository.create_invitation(
            institution_id="hospital-a",
            patient_sno="patient-1",
            reg_sno="visit-1",
            prefill={},
            actor_sub="doctor-1",
        )
        exchanged = self.repository.exchange_invitation(invitation["token"])
        session = self.repository.get_patient_session(exchanged["session_token"])
        created = self.repository.create_with_identifiers(
            {
                "summary": "summary",
                "report": "report",
                "data": {},
                "invitation_id": session["invite_id"],
                "institution_id": session["institution_id"],
                "patient_sno": session["patient_sno"],
                "reg_sno": session["reg_sno"],
            }
        )

        self.assertIsNotNone(
            self.repository.get(created["consultation_id"], institution_id="hospital-a")
        )
        self.assertIsNone(
            self.repository.get(created["consultation_id"], institution_id="hospital-b")
        )
        restored = self.repository.get_patient_session(exchanged["session_token"])
        self.assertEqual(restored["consultation_id"], created["consultation_id"])


if __name__ == "__main__":
    unittest.main()
