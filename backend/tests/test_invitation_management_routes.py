import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import invitations
from app.security import UccPrincipal, authenticate_ucc_request
from infrastructure.consultation_repository import ConsultationRepository


class InvitationManagementRouteTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repository = ConsultationRepository(Path(directory.name) / "test.db")
        self.invite = self.repository.create_invitation(
            institution_id="hospital-a",
            patient_sno="synthetic",
            reg_sno="visit",
            prefill={},
            actor_sub="service",
        )
        self.principal = UccPrincipal(
            "doctor", "hospital-a", frozenset({"consultation:read", "invite:create"}), {}
        )
        app = FastAPI()
        app.include_router(invitations.router)
        app.dependency_overrides[authenticate_ucc_request] = lambda: self.principal
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        repository_patch = patch.object(
            invitations.runtime, "consultation_repository", self.repository
        )
        repository_patch.start()
        self.addCleanup(repository_patch.stop)

    def test_list_validation_and_token_redaction(self):
        response = self.client.get("/doctor/invitations")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.json()["total"], 1)
        self.assertNotIn("token", response.text)
        for query in ("limit=0", "limit=101", "offset=-1", "status=unknown"):
            self.assertEqual(self.client.get("/doctor/invitations?" + query).status_code, 422)

    def test_scopes_and_service_identity_fail_closed(self):
        for scopes, claims in (
            ({"invite:create"}, {}),
            ({"consultation:read", "invite:create"}, {"token_use": "ucc_service"}),
        ):
            self.principal = UccPrincipal("doctor", "hospital-a", frozenset(scopes), claims)
            self.assertEqual(self.client.get("/doctor/invitations").status_code, 403)
        self.principal = UccPrincipal("doctor", "hospital-a", frozenset({"consultation:read"}), {})
        self.assertEqual(self.client.get("/doctor/invitations").status_code, 200)
        for action in ("cancel", "reissue"):
            self.assertEqual(
                self.client.post(
                    f"/doctor/invitations/{self.invite['invite_id']}/{action}"
                ).status_code,
                403,
            )

    def test_cross_institution_matches_absent_resource(self):
        self.principal = UccPrincipal("doctor", "hospital-b", self.principal.scopes, {})
        self.assertEqual(self.client.get("/doctor/invitations").json()["total"], 0)
        with patch.dict(os.environ, {"PATIENT_PUBLIC_BASE_URL": "https://patient.example.test"}):
            for action in ("cancel", "reissue"):
                self.assertEqual(
                    self.client.post(
                        f"/doctor/invitations/{self.invite['invite_id']}/{action}"
                    ).status_code,
                    404,
                )

    def test_reissue_validates_url_before_mutation_and_returns_uncached_new_link(self):
        url = f"/doctor/invitations/{self.invite['invite_id']}/reissue"
        with patch.dict(os.environ, {"PATIENT_PUBLIC_BASE_URL": ""}):
            self.assertEqual(self.client.post(url).status_code, 503)
        self.assertEqual(
            self.repository.list_invitations(institution_id="hospital-a")["items"][0]["status"],
            "active",
        )
        with patch.dict(os.environ, {"PATIENT_PUBLIC_BASE_URL": "https://patient.example.test"}):
            response = self.client.post(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertTrue(
                response.json()["public_url"].startswith("https://patient.example.test/#token=")
            )
            self.assertEqual(self.client.post(url).status_code, 409)
