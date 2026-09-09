import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.models import ChatRequest, FhirCompositionCreateRequest, FhirPatientContext
from app.routes import doctor, patient
from app.security import UccPrincipal
from app.services.fhir_composition import (
    TW_CORE_COMPOSITION_PROFILE,
    build_tw_core_composition,
)
from infrastructure.consultation_repository import ConsultationRepository
from infrastructure.fhir_client import FhirClient, FhirWriteResult


def _sections():
    return [
        {
            "key": key,
            "label": label,
            "value": f"{key} reviewed <safe> & complete",
            "confirmed": True,
        }
        for key, label in (
            ("Chief Complaint", "主訴"),
            ("Present Illness", "現病史"),
            ("Past History", "過去病史"),
            ("Drug History", "用藥史"),
            ("Allergy History", "過敏史"),
            ("Personal History", "個人史"),
            ("Family History", "家族病史"),
        )
    ]


class _Response:
    def __init__(self, payload, *, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def getcode(self):
        return self.status


class FhirCompositionTests(unittest.TestCase):
    def test_request_requires_exact_confirmed_nonblank_sections(self):
        request = FhirCompositionCreateRequest(
            expected_updated_at="2026-08-25T00:00:00Z",
            sections=_sections(),
        )
        self.assertEqual(len(request.sections), 7)

        broken = _sections()
        broken[0]["confirmed"] = False
        with self.assertRaises(ValueError):
            FhirCompositionCreateRequest(
                expected_updated_at="2026-08-25T00:00:00Z",
                sections=broken,
            )

        with self.assertRaises(ValueError):
            FhirPatientContext(patient_id="../other", source="smart")

    def test_browser_fhir_context_requires_explicit_sandbox_ingress(self):
        request = ChatRequest(
            session_id="synthetic-session",
            fhir_context={
                "patient_id": "patient-1",
                "encounter_id": "encounter-1",
                "source": "smart",
            },
        )
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(HTTPException, "FHIR context 匯入未啟用"):
                patient._questionnaire_initial_session(request)

        with patch.dict(
            os.environ,
            {
                "FHIR_PATIENT_CONTEXT_INPUT_ENABLED": "true",
                "FHIR_PUBLIC_ISSUER": "http://fhir.test/r4",
            },
            clear=True,
        ):
            session = patient._questionnaire_initial_session(request)
        self.assertEqual(
            session["fhir_context"],
            {
                "patient_id": "patient-1",
                "encounter_id": "encounter-1",
                "source": "smart",
                "issuer": "http://fhir.test/r4",
            },
        )

    def test_builder_uses_tw_core_references_and_escapes_xhtml(self):
        sections = _sections()
        sections[0]["value"] += "\nSecond line"
        request = FhirCompositionCreateRequest(
            expected_updated_at="2026-08-25T00:00:00Z",
            sections=sections,
        )
        resource = build_tw_core_composition(
            consultation_id="hospital-a:2026-08-25:10000",
            patient_id="patient-1",
            encounter_id="encounter-1",
            sections=request.sections,
            author_reference="Practitioner/doctor-1",
            author_identifier=None,
            author_display="Synthetic Doctor",
            authored_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        )

        self.assertEqual(resource["meta"]["profile"], [TW_CORE_COMPOSITION_PROFILE])
        self.assertEqual(resource["subject"]["reference"], "Patient/patient-1")
        self.assertEqual(resource["encounter"]["reference"], "Encounter/encounter-1")
        self.assertEqual(resource["status"], "preliminary")
        narrative = resource["section"][0]["text"]["div"]
        self.assertIn("&lt;safe&gt; &amp; complete", narrative)
        self.assertIn("<br/>Second line", narrative)
        self.assertNotIn("<safe>", narrative)

    def test_route_rejects_unsigned_author_and_stale_record(self):
        principal = UccPrincipal(
            "doctor-1",
            "hospital-a",
            frozenset({"consultation:read", "consultation:fhir-write"}),
            {},
        )
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(HTTPException, "Practitioner"):
                doctor._composition_author(principal)

        with tempfile.TemporaryDirectory() as directory:
            repository = ConsultationRepository(Path(directory) / "stale.db")
            created = repository.create_with_identifiers(
                {
                    "type": "headache",
                    "summary": "Synthetic summary",
                    "report": "Synthetic report",
                    "data": {"name": "Synthetic Patient"},
                    "institution_id": "hospital-a",
                    "fhir_context": {
                        "issuer": "http://fhir.test/r4",
                        "patient_id": "patient-1",
                    },
                }
            )
            request = FhirCompositionCreateRequest(
                expected_updated_at="stale-version",
                sections=_sections(),
            )
            with (
                patch.object(doctor.runtime, "consultation_repository", repository),
                patch.object(doctor, "current_ucc_principal", return_value=principal),
            ):
                with self.assertRaisesRegex(HTTPException, "病例已更新"):
                    doctor.create_fhir_composition(created["consultation_id"], request)

    def test_existing_submission_is_idempotently_returned_without_fhir_call(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = ConsultationRepository(Path(directory) / "existing.db")
            created = repository.create_with_identifiers(
                {
                    "type": "headache",
                    "summary": "Synthetic summary",
                    "report": "Synthetic report",
                    "data": {"name": "Synthetic Patient"},
                    "institution_id": "hospital-a",
                    "fhir_context": {
                        "issuer": "http://fhir.test/r4",
                        "patient_id": "patient-1",
                    },
                }
            )
            original = repository.get(created["consultation_id"])
            repository.save_fhir_submission(
                created["consultation_id"],
                resource_id="composition-existing",
                version_id="2",
                submitted_by="doctor-1",
                sections=_sections(),
            )
            saved = repository.get(created["consultation_id"])
            request = FhirCompositionCreateRequest(
                # Simulate retrying the original request after the first response was lost.
                expected_updated_at=original["updated_at"],
                sections=_sections(),
            )
            principal = UccPrincipal(
                "doctor-1",
                "hospital-a",
                frozenset({"consultation:read", "consultation:fhir-write"}),
                {"fhirUser": "Practitioner/doctor-1"},
            )
            with (
                patch.object(doctor.runtime, "consultation_repository", repository),
                patch.object(doctor, "current_ucc_principal", return_value=principal),
            ):
                response = doctor.create_fhir_composition(
                    created["consultation_id"],
                    request,
                )
            self.assertEqual(response["status"], "existing")
            self.assertEqual(response["resource_id"], "composition-existing")
            self.assertNotEqual(saved["updated_at"], request.expected_updated_at)

    def test_client_verifies_refs_and_conditionally_creates_composition(self):
        requests = []
        responses = iter(
            [
                _Response({"resourceType": "Patient", "id": "patient-1"}),
                _Response({"resourceType": "Encounter", "id": "encounter-1"}),
                _Response(
                    {
                        "resourceType": "Composition",
                        "id": "composition-1",
                        "meta": {"versionId": "3"},
                    },
                    status=201,
                ),
            ]
        )

        def opener(request, **_kwargs):
            requests.append(request)
            return next(responses)

        client = FhirClient("http://fhir.test/r4", opener=opener)
        client.read_resource("Patient", "patient-1")
        client.read_resource("Encounter", "encounter-1")
        result = client.create_composition(
            {
                "resourceType": "Composition",
                "identifier": {"system": "https://example.test/note", "value": "case-1"},
            }
        )

        self.assertEqual(result.resource_id, "composition-1")
        self.assertEqual(result.version_id, "3")
        self.assertTrue(result.created)
        self.assertEqual(requests[2].method, "POST")
        self.assertEqual(requests[2].get_header("Content-type"), "application/fhir+json")
        self.assertIn("identifier=", requests[2].get_header("If-none-exist"))

    def test_route_writes_only_bound_tenant_record_and_persists_result(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = ConsultationRepository(Path(directory) / "fhir.db")
            created = repository.create_with_identifiers(
                {
                    "type": "headache",
                    "summary": "Synthetic summary",
                    "report": "Synthetic report",
                    "data": {"name": "Synthetic Patient"},
                    "institution_id": "hospital-a",
                    "fhir_context": {
                        "issuer": "http://fhir.test/r4",
                        "patient_id": "patient-1",
                        "encounter_id": "encounter-1",
                    },
                }
            )
            saved = repository.get(
                created["consultation_id"],
                institution_id="hospital-a",
            )
            request = FhirCompositionCreateRequest(
                expected_updated_at=saved["updated_at"],
                sections=_sections(),
            )

            class Client:
                enabled = True
                base_url = "http://fhir.test/r4"

                def __init__(self):
                    self.reads = []

                def read_resource(self, resource_type, resource_id):
                    self.reads.append((resource_type, resource_id))
                    return {"resourceType": resource_type, "id": resource_id}

                def create_composition(self, composition):
                    self.composition = composition
                    return FhirWriteResult("composition-1", "1", True)

            client = Client()
            principal = UccPrincipal(
                "doctor-1",
                "hospital-a",
                frozenset({"consultation:read", "consultation:fhir-write"}),
                {"fhirUser": "Practitioner/doctor-1", "name": "Synthetic Doctor"},
            )
            with (
                patch.object(doctor.runtime, "consultation_repository", repository),
                patch.object(doctor.runtime, "fhir_client", client),
                patch.object(doctor, "current_ucc_principal", return_value=principal),
                patch.dict(os.environ, {"FHIR_PUBLIC_ISSUER": "http://fhir.test/r4"}),
            ):
                response = doctor.create_fhir_composition(
                    created["consultation_id"],
                    request,
                )

            self.assertEqual(response["status"], "created")
            self.assertEqual(
                client.reads,
                [("Patient", "patient-1"), ("Encounter", "encounter-1")],
            )
            persisted = repository.get(created["consultation_id"])
            self.assertEqual(
                persisted["fhir_submission"]["resource_id"],
                "composition-1",
            )
            self.assertEqual(len(persisted["fhir_summary_sections"]), 7)


if __name__ == "__main__":
    unittest.main()
