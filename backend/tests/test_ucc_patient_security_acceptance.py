import asyncio
import gc
import inspect
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from fastapi import BackgroundTasks, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from app import runtime
from app.models import ChatRequest, InvitationCreateRequest, InvitationExchangeRequest
from app.routes import doctor, invitations, patient, system
from app.security import UccPrincipal, authenticate_ucc, require_scopes
from infrastructure.consultation_repository import ConsultationRepository, SCHEMA_VERSION


ROOT = Path(__file__).resolve().parents[2]
EHIS = Path(r"D:\ehis\eHIS")


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


def _route(router, path: str, method: str):
    return next(
        route
        for route in router.routes
        if route.path == path and method.upper() in route.methods
    )


def _required_scopes(route) -> set[str]:
    result: set[str] = set()
    for item in route.dependant.dependencies:
        dependency = item.call
        for cell in dependency.__closure__ or ():
            value = cell.cell_contents
            if isinstance(value, tuple) and all(isinstance(scope, str) for scope in value):
                result.update(value)
    return result


class UccJwtAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public_pem = cls.private_key.public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
        ).decode("ascii")
        cls.private_pem = cls.private_key.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        ).decode("ascii")
        forged_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.forged_private_pem = forged_private.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        ).decode("ascii")

    def _claims(self, **overrides):
        now = datetime.now(timezone.utc)
        claims = {
            "iss": "ucc-ehis",
            "aud": "medical-consultation-api",
            "sub": "doctor-1",
            "institution_id": "hospital-a",
            "scope": "consultation:read invite:create",
            "scopes": ["rules:read"],
            "jti": "test-jti",
            "iat": now,
            "nbf": now - timedelta(seconds=1),
            "exp": now + timedelta(minutes=5),
        }
        claims.update(overrides)
        return claims

    def _authenticate(self, claims=None, *, key=None):
        token = jwt.encode(
            claims or self._claims(),
            key or self.private_pem,
            algorithm="RS256",
        )
        env = {
            "UCC_JWT_PUBLIC_KEY": self.public_pem,
            "UCC_JWT_ISSUER": "ucc-ehis",
            "UCC_JWT_AUDIENCE": "medical-consultation-api",
        }
        with patch.dict(os.environ, env, clear=False):
            return authenticate_ucc(
                _request(),
                HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
            )

    def assert_rejected(self, claims, *, key=None, status_code=401):
        with self.assertRaises(HTTPException) as raised:
            self._authenticate(claims, key=key)
        self.assertEqual(raised.exception.status_code, status_code)

    def test_valid_rs256_token_and_both_scope_claim_forms(self):
        principal = self._authenticate()
        self.assertEqual(principal.subject, "doctor-1")
        self.assertEqual(principal.institution_id, "hospital-a")
        self.assertEqual(
            principal.scopes,
            {"consultation:read", "invite:create", "rules:read"},
        )

    def test_forged_expired_future_nbf_wrong_issuer_and_wrong_audience_are_rejected(self):
        now = datetime.now(timezone.utc)
        cases = [
            (self._claims(exp=now - timedelta(seconds=1)), None),
            (self._claims(nbf=now + timedelta(minutes=5)), None),
            (self._claims(iss="other-issuer"), None),
            (self._claims(aud="other-audience"), None),
            (self._claims(), self.forged_private_pem),
        ]
        for claims, key in cases:
            with self.subTest(claims=claims, forged=key is not None):
                self.assert_rejected(claims, key=key)

    def test_required_claims_and_scopes_are_enforced(self):
        for missing in ("exp", "iat", "iss", "aud", "sub", "jti"):
            claims = self._claims()
            claims.pop(missing)
            with self.subTest(missing=missing):
                self.assert_rejected(claims)

        no_scope = UccPrincipal("doctor", "hospital-a", frozenset(), {})
        with self.assertRaises(HTTPException) as raised:
            require_scopes("invite:create")(principal=no_scope)
        self.assertEqual(raised.exception.status_code, 403)

        no_institution = self._claims()
        no_institution.pop("institution_id")
        self.assert_rejected(no_institution, status_code=403)


class InvitationAndSessionAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "integration.db"
        self.repository = ConsultationRepository(self.database_path)

    def tearDown(self):
        # sqlite3.Connection context managers commit/rollback but do not close;
        # force collection before Windows removes the WAL-backed temp database.
        del self.repository
        gc.collect()
        self.temp_directory.cleanup()

    def _invite(self, institution="hospital-a", patient_sno="patient-1", reg_sno="visit-1", **kwargs):
        return self.repository.create_invitation(
            institution_id=institution,
            patient_sno=patient_sno,
            reg_sno=reg_sno,
            prefill={"name": patient_sno},
            actor_sub="doctor-1",
            **kwargs,
        )

    def test_default_lifetimes_revocation_single_use_hashing_and_audit(self):
        before = datetime.now(timezone.utc)
        old = self._invite()
        after = datetime.now(timezone.utc)
        expiry = datetime.fromisoformat(old["expires_at"])
        self.assertGreaterEqual(expiry, before + timedelta(hours=24) - timedelta(seconds=2))
        self.assertLessEqual(expiry, after + timedelta(hours=24) + timedelta(seconds=2))

        replacement = self._invite()
        with self.assertRaisesRegex(ValueError, "used or revoked"):
            self.repository.exchange_invitation(old["token"])
        exchanged = self.repository.exchange_invitation(replacement["token"])
        with self.assertRaisesRegex(ValueError, "used or revoked"):
            self.repository.exchange_invitation(replacement["token"])

        session_expiry = datetime.fromisoformat(exchanged["expires_at"])
        self.assertGreaterEqual(session_expiry, before + timedelta(hours=8) - timedelta(seconds=2))
        self.assertLessEqual(session_expiry, datetime.now(timezone.utc) + timedelta(hours=8, seconds=2))

        with closing(sqlite3.connect(self.database_path)) as connection:
            invitations_rows = connection.execute(
                "SELECT token_hash, status FROM invitations ORDER BY created_at"
            ).fetchall()
            patient_token_hash = connection.execute(
                "SELECT session_token_hash FROM patient_sessions"
            ).fetchone()[0]
            audit_actions = [
                row[0]
                for row in connection.execute("SELECT action FROM audit_events ORDER BY id")
            ]
        self.assertNotIn(old["token"], {row[0] for row in invitations_rows})
        self.assertNotEqual(patient_token_hash, exchanged["session_token"])
        self.assertEqual([row[1] for row in invitations_rows], ["revoked", "consumed"])
        self.assertEqual(
            audit_actions,
            [
                "invitation.create",
                "invitation.create",
                "invitation.exchange",
                "invitation.exchange",
                "invitation.exchange",
            ],
        )

    def test_invitation_and_session_expiry(self):
        expired = self._invite(ttl_seconds=-1)
        self.assertIsNone(self.repository.exchange_invitation(expired["token"]))
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM invitations WHERE invite_id = ?", (expired["invite_id"],)
                ).fetchone()[0],
                "expired",
            )

        active = self._invite(reg_sno="visit-2")
        exchanged = self.repository.exchange_invitation(active["token"], session_ttl_seconds=-1)
        self.assertIsNone(self.repository.get_patient_session(exchanged["session_token"]))

    def test_patient_and_institution_isolation_and_consultation_link(self):
        first = self._invite("hospital-a", "patient-a", "same-visit")
        second = self._invite("hospital-b", "patient-b", "same-visit")
        first_exchange = self.repository.exchange_invitation(first["token"])
        second_exchange = self.repository.exchange_invitation(second["token"])
        first_session = self.repository.get_patient_session(first_exchange["session_token"])
        second_session = self.repository.get_patient_session(second_exchange["session_token"])
        self.assertEqual(first_session["patient_sno"], "patient-a")
        self.assertEqual(second_session["patient_sno"], "patient-b")

        created = self.repository.create_with_identifiers(
            {
                "type": "chest",
                "summary": "summary",
                "report": "report",
                "data": {},
                "invitation_id": first_session["invite_id"],
                "institution_id": first_session["institution_id"],
                "patient_sno": first_session["patient_sno"],
                "reg_sno": first_session["reg_sno"],
            }
        )
        self.assertIsNotNone(
            self.repository.get(created["consultation_id"], institution_id="hospital-a")
        )
        self.assertIsNone(
            self.repository.get(created["consultation_id"], institution_id="hospital-b")
        )
        self.assertEqual(
            self.repository.get_patient_session(first_exchange["session_token"])["consultation_id"],
            created["consultation_id"],
        )
        self.assertIsNone(self.repository.get_patient_session("not-the-other-patient-token"))

    def test_exchange_sets_secure_httponly_samesite_cookie_and_session_restores(self):
        invitation = self._invite()
        response = Response()
        with patch.object(runtime, "consultation_repository", self.repository), patch.dict(
            os.environ, {"PATIENT_COOKIE_SECURE": "true"}, clear=False
        ):
            payload = InvitationExchangeRequest(token=invitation["token"])
            result = invitations.exchange_invitation(payload, response)
        self.assertEqual(result["status"], "ok")
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("secure", cookie)
        self.assertIn("samesite=lax", cookie)
        self.assertIn("max-age=28800", cookie)
        self.assertNotIn(invitation["token"].lower(), cookie)

        session_token = response.headers["set-cookie"].split("=", 1)[1].split(";", 1)[0]
        self.assertIsNotNone(self.repository.get_patient_session(session_token))

    def test_patient_chat_ignores_attacker_supplied_session_and_prefill(self):
        invitation = self._invite(patient_sno="patient-a")
        exchange = self.repository.exchange_invitation(invitation["token"])
        bound = self.repository.get_patient_session(exchange["session_token"])
        request = ChatRequest(
            session_id="attacker-selected-session",
            patient_prefill={"name": "attacker name"},
        )
        isolated_sessions = {}
        with patch.object(patient, "INTERVIEW_ENGINE", "legacy"), patch.object(
            patient, "sessions", isolated_sessions
        ), patch.object(patient, "current_patient_session", return_value=bound):
            result = asyncio.run(patient.chat(request, BackgroundTasks()))
        self.assertEqual(result["session_id"], bound["interview_session_id"])
        self.assertNotIn("attacker-selected-session", isolated_sessions)
        self.assertEqual(isolated_sessions[bound["interview_session_id"]]["data"]["name"], "patient-a")

    def test_patient_interview_restores_after_restart_beyond_thirty_minutes(self):
        invitation = self._invite(patient_sno="patient-a")
        exchange = self.repository.exchange_invitation(invitation["token"])
        bound = self.repository.get_patient_session(exchange["session_token"])
        isolated_sessions = {}

        with patch.object(patient, "INTERVIEW_ENGINE", "legacy"), patch.object(
            patient, "sessions", isolated_sessions
        ), patch.object(
            patient, "consultation_repository", self.repository
        ), patch.object(
            patient, "current_patient_session", return_value=bound
        ):
            started = asyncio.run(
                patient.chat(ChatRequest(session_id="ignored"), BackgroundTasks())
            )
            self.assertEqual(started["session_id"], bound["interview_session_id"])

            persisted = self.repository.load_patient_runtime_state(
                **patient._patient_runtime_binding(bound)
            )
            persisted["ts"] = (
                datetime.now(timezone.utc) - timedelta(minutes=31)
            ).timestamp()
            self.assertTrue(
                self.repository.save_patient_runtime_state(
                    **patient._patient_runtime_binding(bound),
                    state=persisted,
                )
            )

            # Simulate a new process: its in-memory runtime has no interview.
            isolated_sessions.clear()
            with patch.object(
                patient, "_assess_chief_complaint", return_value=("headache", [])
            ):
                continued = asyncio.run(
                    patient.chat(
                        ChatRequest(session_id="attacker", message="headache"),
                        BackgroundTasks(),
                    )
                )

        self.assertEqual(continued["session_id"], bound["interview_session_id"])
        self.assertEqual(
            isolated_sessions[bound["interview_session_id"]]["data"]["reason"],
            "headache",
        )
        reopened = ConsultationRepository(self.database_path)
        durable = reopened.load_patient_runtime_state(
            **patient._patient_runtime_binding(bound)
        )
        self.assertEqual(durable["data"]["reason"], "headache")

    def test_runtime_state_is_patient_bound_bounded_and_expires_with_eight_hour_session(self):
        invitation = self._invite(patient_sno="patient-a")
        exchange = self.repository.exchange_invitation(invitation["token"])
        bound = self.repository.get_patient_session(exchange["session_token"])
        binding = patient._patient_runtime_binding(bound)
        state = {"session_id": bound["interview_session_id"], "data": {}}
        self.assertTrue(
            self.repository.save_patient_runtime_state(**binding, state=state)
        )
        self.assertIsNone(
            self.repository.load_patient_runtime_state(
                **{**binding, "patient_sno": "another-patient"}
            )
        )
        with self.assertRaisesRegex(ValueError, "storage limit"):
            self.repository.save_patient_runtime_state(
                **binding,
                state={
                    "session_id": bound["interview_session_id"],
                    "data": {"oversized": "x" * (513 * 1024)},
                },
            )

        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                "UPDATE patient_sessions SET expires_at = ? WHERE session_id = ?",
                (
                    (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                    bound["session_id"],
                ),
            )
            connection.commit()
        self.assertIsNone(self.repository.get_patient_session(exchange["session_token"]))
        self.assertIsNone(self.repository.load_patient_runtime_state(**binding))


class SchemaAndRouteAcceptanceTests(unittest.TestCase):
    def test_v8_schema_wal_tables_columns_and_foreign_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v6.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE consultations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        queue_number TEXT NOT NULL UNIQUE,
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
                        triage_level TEXT NOT NULL DEFAULT 'routine',
                        workflow_status TEXT NOT NULL DEFAULT 'completed',
                        consultation_date TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    PRAGMA user_version = 6;
                    """
                )
            ConsultationRepository(path)
            with closing(sqlite3.connect(path)) as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                journal = connection.execute("PRAGMA journal_mode").fetchone()[0]
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(consultations)")
                }
                patient_session_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(patient_sessions)")
                }
                foreign_keys = connection.execute("PRAGMA foreign_key_list(patient_sessions)").fetchall()
            self.assertEqual(version, SCHEMA_VERSION, 7)
            self.assertEqual(journal.casefold(), "wal")
            self.assertTrue({"invitations", "patient_sessions", "audit_events"} <= tables)
            self.assertTrue(
                {"invitation_id", "institution_id", "patient_sno", "reg_sno"} <= columns
            )
            self.assertTrue(
                {"runtime_state_json", "runtime_updated_at"} <= patient_session_columns
            )
            self.assertTrue(any(row[2] == "invitations" and row[3] == "invite_id" for row in foreign_keys))

    def test_patient_doctor_transcribe_and_rule_route_scopes(self):
        self.assertEqual(
            _required_scopes(_route(doctor.router, "/doctor/consultations", "GET")),
            {"consultation:read"},
        )
        self.assertEqual(
            _required_scopes(
                _route(doctor.router, "/doctor/consultations/{consultation_id}", "DELETE")
            ),
            {"consultation:read", "consultation:delete"},
        )
        ordinary_doctor = UccPrincipal(
            "doctor", "hospital-a", frozenset({"consultation:read"}), {}
        )
        with self.assertRaises(HTTPException) as denied:
            require_scopes("consultation:delete")(principal=ordinary_doctor)
        self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual(
            _required_scopes(_route(doctor.router, "/doctor/chat", "POST")),
            {"consultation:read", "consultation:chat"},
        )
        self.assertEqual(
            _required_scopes(_route(doctor.router, "/doctor/rules", "GET")),
            {"consultation:read", "rules:read"},
        )
        self.assertEqual(
            _required_scopes(_route(doctor.router, "/doctor/rules/safety", "PUT")),
            {"consultation:read", "rules:write"},
        )
        self.assertIn(
            "require_patient_session",
            {
                dependency.call.__name__
                for dependency in _route(patient.router, "/chat", "POST").dependant.dependencies
            },
        )
        self.assertIn(
            "require_patient_session",
            {
                dependency.call.__name__
                for dependency in _route(system.router, "/transcribe", "POST").dependant.dependencies
            },
        )

    def test_cors_is_allowlist_only_and_deployment_disables_aliases(self):
        source = (ROOT / "backend" / "app" / "factory.py").read_text(encoding="utf-8")
        self.assertIn('os.getenv("CORS_ALLOWED_ORIGINS", "")', source)
        self.assertNotIn('allow_origins=["*"]', source.replace(" ", ""))
        env_example = (ROOT / "integration-deployment" / ".env.example").read_text(
            encoding="utf-8"
        )
        self.assertIn("ENABLE_UNVERSIONED_ALIASES=false", env_example)
        self.assertIn("CORS_ALLOWED_ORIGINS=", env_example)
        compose = (ROOT / "integration-deployment" / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('ENABLE_UNVERSIONED_ALIASES: "false"', compose)

    def test_actual_ehis_invitation_json_shape_is_accepted_by_backend(self):
        # AiConsultPatientPrefill currently serializes these fields as JSON arrays.
        payload = InvitationCreateRequest.model_validate(
            {
                "institution_id": "hospital-a",
                "patient_sno": 10,
                "reg_sno": 20,
                "prefill": {
                    "name": "Patient",
                    "allergies": ["penicillin", "latex"],
                    "current_medications": ["aspirin"],
                    "medical_history": ["hypertension"],
                    "surgical_history": ["appendectomy"],
                },
            }
        )
        normalized = payload.prefill.as_patient_prefill()
        self.assertIn("penicillin", normalized["allergy"])
        self.assertIn("latex", normalized["allergy"])


class EhisStaticContractTests(unittest.TestCase):
    def test_controller_enforces_menu_encounter_csrf_and_expected_contract(self):
        controller = (EHIS / "Controllers" / "AiConsultController.cs").read_text(
            encoding="utf-8"
        )
        self.assertIn("[ValidateAntiForgeryToken]", controller)
        self.assertGreaterEqual(controller.count('HasMenuPermission("Index")'), 3)
        self.assertGreaterEqual(controller.count("GetAccessibleEncounterAsync"), 2)
        self.assertIn('HasMenuPermission("RuleCenter")', controller)
        self.assertIn('new[] { "invite:create" }', controller)
        doctor_scopes = controller.split("private static readonly string[] DoctorScopes", 1)[1].split("};", 1)[0]
        self.assertNotIn('"invite:create"', doctor_scopes)
        self.assertIn('"doctor"', controller)
        self.assertIn('"ucc_service"', controller)
        self.assertIn("_antiforgery.GetAndStoreTokens(HttpContext)", controller)
        self.assertIn("CsrfToken = csrf.RequestToken", controller)

        models = (EHIS / "Models" / "AiConsultModels.cs").read_text(encoding="utf-8")
        for json_name in (
            "institution_id",
            "patient_sno",
            "reg_sno",
            "prefill",
            "csrf_token",
        ):
            self.assertIn(f'JsonPropertyName("{json_name}")', models)

    def test_rs256_claims_short_ttl_certificate_store_and_gateway(self):
        security = (EHIS / "Services" / "AiConsult" / "AiConsultSecurity.cs").read_text(
            encoding="utf-8"
        )
        for claim in (
            '["iss"]',
            '["aud"]',
            '["sub"]',
            '["institution_id"]',
            '["reg_sno"]',
            '["token_use"]',
            '["scope"]',
            '["scopes"]',
            '["jti"]',
            '["iat"]',
            '["nbf"]',
            '["exp"]',
        ):
            self.assertIn(claim, security)
        self.assertIn('["alg"] = "RS256"', security)
        self.assertIn("Math.Clamp(options.JwtTtlMinutes, 1, 15)", security)
        self.assertIn("new X509Store(storeName, location)", security)
        self.assertIn("RSASignaturePadding.Pkcs1", security)

        gateway = (EHIS / "Services" / "AiConsult" / "AiConsultIntegration.cs").read_text(
            encoding="utf-8"
        )
        # Keep this contract focused on the gateway's security semantics instead
        # of the exact formatting of its URI construction.
        self.assertIn("Uri.TryCreate(options.BackendBaseUrl, UriKind.Absolute", gateway)
        for disallowed_component in (
            "backendUri.UserInfo",
            "backendUri.Query",
            "backendUri.Fragment",
        ):
            self.assertIn(disallowed_component, gateway)
        self.assertIn("Uri.UriSchemeHttps", gateway)
        self.assertIn("AllowDevelopmentLoopbackHttp", gateway)
        self.assertIn("backendUri.IsLoopback", gateway)
        self.assertIn("new UriBuilder(backendUri)", gateway)
        self.assertIn("baseBuilder.Path.EndsWith", gateway)
        self.assertIn('new Uri(baseBuilder.Uri, "v1/invitations")', gateway)
        for origin_component in ("endpoint.Scheme", "endpoint.Host", "endpoint.Port"):
            self.assertIn(origin_component, gateway)
        self.assertIn("AuthenticationHeaderValue(\"Bearer\", serviceToken)", gateway)

        startup = (EHIS / "Startup.cs").read_text(encoding="utf-8")
        self.assertIn("AllowAutoRedirect = false", startup)

        view = (EHIS / "Views" / "AiConsult" / "Index.cshtml").read_text(encoding="utf-8")
        self.assertIn("/ai-consult/index.html", view)
        self.assertIn("#/doctor", view)


if __name__ == "__main__":
    unittest.main()
