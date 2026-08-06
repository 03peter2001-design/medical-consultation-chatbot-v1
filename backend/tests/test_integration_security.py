import gc
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.models import InvitationCreateRequest, InvitationPrefill
from app.security import _claim_scopes
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
