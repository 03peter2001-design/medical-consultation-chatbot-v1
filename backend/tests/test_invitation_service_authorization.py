import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.models import InvitationCreateRequest
from app.routes import invitations
from app.security import UccPrincipal


class _InvitationRepository:
    def __init__(self):
        self.calls = []

    def create_invitation(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "invite_id": "invite-1",
            "token": "opaque-token",
            "expires_at": "2099-01-01T00:00:00Z",
            "status": "active",
        }


def _principal(
    *,
    institution_id="hospital-a",
    reg_sno=20,
    token_use="ucc_service",
    subject=None,
):
    claims = {
        "institution_id": institution_id,
        "reg_sno": reg_sno,
    }
    if token_use is not None:
        claims["token_use"] = token_use
    return UccPrincipal(
        subject or f"ucc-service:{institution_id}",
        institution_id,
        frozenset({"invite:create"}),
        claims,
    )


class InvitationServiceAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.payload = InvitationCreateRequest.model_validate(
            {
                "institution_id": "hospital-a",
                "patient_sno": 10,
                "reg_sno": 20,
                "prefill": {"name": "Patient"},
            }
        )

    def assert_service_denied(self, principal):
        with self.assertRaises(HTTPException) as raised:
            invitations.require_invitation_service(principal=principal)
        self.assertEqual(raised.exception.status_code, 403)

    def test_doctor_bootstrap_token_cannot_be_used_as_invitation_service(self):
        self.assert_service_denied(
            _principal(token_use="doctor", subject="doctor-1")
        )

    def test_missing_or_wrong_token_use_and_wrong_subject_are_denied(self):
        self.assert_service_denied(_principal(token_use=None))
        self.assert_service_denied(_principal(token_use="other"))
        self.assert_service_denied(_principal(subject="doctor-1"))

    def test_service_token_can_create_invitation_for_its_bound_encounter(self):
        repository = _InvitationRepository()
        principal = invitations.require_invitation_service(principal=_principal())
        with (
            patch.object(invitations.runtime, "consultation_repository", repository),
            patch.dict(os.environ, {"PATIENT_PUBLIC_BASE_URL": "https://patient.test"}),
        ):
            result = invitations.create_invitation(self.payload, principal=principal)

        self.assertEqual(result["invite_id"], "invite-1")
        self.assertEqual(len(repository.calls), 1)
        self.assertEqual(repository.calls[0]["patient_sno"], "10")
        self.assertEqual(repository.calls[0]["reg_sno"], "20")

    def test_reg_sno_mismatch_is_denied(self):
        principal = invitations.require_invitation_service(
            principal=_principal(reg_sno=21)
        )
        with self.assertRaises(HTTPException) as raised:
            invitations.create_invitation(self.payload, principal=principal)
        self.assertEqual(raised.exception.status_code, 403)

    def test_institution_mismatch_is_denied(self):
        principal = invitations.require_invitation_service(
            principal=_principal(institution_id="hospital-b")
        )
        with self.assertRaises(HTTPException) as raised:
            invitations.create_invitation(self.payload, principal=principal)
        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
