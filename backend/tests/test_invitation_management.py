import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from pathlib import Path
from threading import Barrier

from infrastructure.consultation_repository import ConsultationRepository


class InvitationManagementTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "test.db"
        self.repository = ConsultationRepository(self.path)

    def create(self, institution="hospital-a", reg="visit-1", ttl=300):
        return self.repository.create_invitation(
            institution_id=institution,
            patient_sno="synthetic-patient",
            reg_sno=reg,
            prefill={"name": "Synthetic Patient"},
            actor_sub="doctor",
            ttl_seconds=ttl,
            fhir_context={"issuer": "https://fhir.example.test", "patient_id": "synthetic"},
        )

    def manage(self, invite, reissue=False, institution="hospital-a"):
        return self.repository.manage_invitation(
            institution_id=institution,
            invite_id=invite["invite_id"],
            actor_sub="doctor",
            reissue=reissue,
        )

    def test_listing_is_scoped_paginated_and_does_not_expose_credentials(self):
        self.create()
        self.create(reg="visit-2", ttl=-1)
        self.create(institution="hospital-b")
        result = self.repository.list_invitations(institution_id="hospital-a", limit=1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["items"]), 1)
        next_page = self.repository.list_invitations(institution_id="hospital-a", limit=1, offset=1)
        self.assertNotEqual(result["items"][0]["invite_id"], next_page["items"][0]["invite_id"])
        self.assertEqual(
            set(result["items"][0]),
            {
                "invite_id",
                "patient_sno",
                "reg_sno",
                "status",
                "created_at",
                "expires_at",
                "consumed_at",
                "consultation_id",
                "replaced_by_invite_id",
                "last_seen_at",
                "session_expires_at",
            },
        )
        expired = self.repository.list_invitations(institution_id="hospital-a", status="expired")
        self.assertEqual(expired["total"], 1)

    def test_cancellation_revokes_exchanged_session_and_is_idempotent(self):
        invite = self.create()
        exchanged = self.repository.exchange_invitation(invite["token"])
        self.assertIsNotNone(self.repository.get_patient_session(exchanged["session_token"]))
        self.assertEqual(self.manage(invite), {"status": "revoked"})
        self.assertEqual(self.manage(invite), {"status": "revoked"})
        self.assertIsNone(self.repository.get_patient_session(exchanged["session_token"]))
        with self.assertRaises(ValueError):
            self.repository.exchange_invitation(invite["token"])
        with self.assertRaisesRegex(ValueError, "revoked"):
            self.repository.create_with_identifiers(
                {"invitation_id": invite["invite_id"], "data": {}}
            )

    def test_other_institution_cannot_cancel_or_reissue(self):
        invite = self.create()
        self.assertIsNone(self.manage(invite, institution="hospital-b"))
        self.assertIsNone(self.manage(invite, reissue=True, institution="hospital-b"))
        self.assertIsNotNone(self.repository.exchange_invitation(invite["token"]))

    def test_completed_invitation_is_immutable(self):
        invite = self.create()
        self.repository.exchange_invitation(invite["token"])
        self.repository.create_with_identifiers({"invitation_id": invite["invite_id"], "data": {}})
        self.assertEqual(
            self.repository.list_invitations(institution_id="hospital-a")["items"][0]["status"],
            "completed",
        )
        for reissue in (False, True):
            with self.assertRaises(ValueError):
                self.manage(invite, reissue=reissue)

    def test_reissue_preserves_binding_ttl_and_replacement_survives_restart(self):
        invite = self.create()
        session = self.repository.exchange_invitation(invite["token"])
        replacement = self.manage(invite, reissue=True)
        self.assertIsNone(self.repository.get_patient_session(session["session_token"]))
        with closing(self.repository._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM invitations WHERE invite_id = ?", (replacement["invite_id"],)
            ).fetchone()
            self.assertEqual(
                (
                    datetime.fromisoformat(row["expires_at"])
                    - datetime.fromisoformat(row["created_at"])
                ).total_seconds(),
                300,
            )
        self.repository = ConsultationRepository(self.path)
        with self.assertRaises(ValueError):
            self.manage(invite, reissue=True)
        exchanged = self.repository.exchange_invitation(replacement["token"])
        restored = self.repository.get_patient_session(exchanged["session_token"])
        self.assertEqual(restored["prefill"], {"name": "Synthetic Patient"})
        self.assertEqual(restored["fhir_context"]["patient_id"], "synthetic")

    def test_concurrent_reissue_has_only_one_winner(self):
        invite = self.create()

        def attempt(_):
            try:
                return self.manage(invite, reissue=True)
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.repository.list_invitations(institution_id="hospital-a")["total"], 2)

    def test_expired_can_be_cancelled_and_old_issue_cannot_displace_newer(self):
        expired = self.create(ttl=-1)
        self.assertEqual(self.manage(expired)["status"], "revoked")
        fresh = self.create()
        with self.assertRaises(ValueError):
            self.manage(expired, reissue=True)
        self.assertIsNotNone(self.repository.exchange_invitation(fresh["token"]))

    def test_completion_and_cancellation_race_has_one_committed_outcome(self):
        invite = self.create()
        self.repository.exchange_invitation(invite["token"])
        barrier = Barrier(2)

        def attempt(complete):
            barrier.wait(timeout=5)
            try:
                if complete:
                    self.repository.create_with_identifiers(
                        {"invitation_id": invite["invite_id"], "data": {}}
                    )
                else:
                    self.manage(invite)
                return True
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            completed, cancelled = list(executor.map(attempt, (True, False)))
        self.assertNotEqual(completed, cancelled)
        item = self.repository.list_invitations(institution_id="hospital-a")["items"][0]
        self.assertEqual(item["status"], "completed" if completed else "revoked")
        self.assertEqual(self.repository.count(), 1 if completed else 0)

    def test_schema_11_migration_preserves_existing_invitation(self):
        invite = self.create()
        with closing(self.repository._connect()) as connection, connection:
            connection.execute("ALTER TABLE invitations DROP COLUMN replaced_by_invite_id")
            connection.execute("PRAGMA user_version = 11")
        self.repository = ConsultationRepository(self.path)
        item = self.repository.list_invitations(institution_id="hospital-a")["items"][0]
        self.assertEqual(item["invite_id"], invite["invite_id"])
        self.assertIsNone(item["replaced_by_invite_id"])
        self.assertIsNotNone(self.repository.exchange_invitation(invite["token"]))
