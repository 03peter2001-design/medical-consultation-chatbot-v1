import asyncio
import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from app.security import authenticate_ucc, current_ucc_principal, require_scopes


def request() -> Request:
    return Request(
        {"type": "http", "method": "GET", "path": "/", "headers": []}
    )


class UccAuthBoundaryTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public_pem = (
            cls.private_key.public_key()
            .public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
            .decode("ascii")
        )

    def claims(self, **overrides):
        now = datetime.now(timezone.utc)
        values = {
            "iss": "ucc-ehis",
            "aud": "medical-consultation-api",
            "sub": "doctor-1",
            "institution_id": "hospital-a",
            "scope": "consultation:read",
            "jti": "test-jti",
            "iat": now,
            "nbf": now - timedelta(seconds=30),
            "exp": now + timedelta(minutes=5),
        }
        values.update(overrides)
        return values

    def token(self, **overrides):
        return jwt.encode(self.claims(**overrides), self.private_key, algorithm="RS256")

    def environment(self, **overrides):
        values = {
            "UCC_JWT_PUBLIC_KEY": self.public_pem,
            "UCC_JWT_ISSUER": "ucc-ehis",
            "UCC_JWT_AUDIENCE": "medical-consultation-api",
            "ALLOW_LOCAL_AUTH_BYPASS": "false",
        }
        values.update(overrides)
        return patch.dict(os.environ, values, clear=False)

    def authenticate(self, token):
        return authenticate_ucc(
            request(),
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
        )

    def test_bounded_clock_skew_accepts_a_slightly_future_iat(self):
        now = datetime.now(timezone.utc)
        with self.environment():
            for claims in (
                {"iat": now + timedelta(seconds=20)},
                {"nbf": now + timedelta(seconds=20)},
                {"exp": now - timedelta(seconds=10)},
            ):
                with self.subTest(claims=claims):
                    principal = self.authenticate(self.token(**claims))
                    self.assertEqual(principal.subject, "doctor-1")

            for claims in (
                {"iat": now + timedelta(minutes=5)},
                {"nbf": now + timedelta(minutes=5)},
                {"exp": now - timedelta(minutes=5)},
            ):
                with self.subTest(claims=claims):
                    with self.assertRaises(HTTPException) as raised:
                        self.authenticate(self.token(**claims))
                    self.assertEqual(raised.exception.status_code, 401)

    def test_configured_clock_skew_bounds_are_enforced(self):
        now = datetime.now(timezone.utc)
        with self.environment(UCC_JWT_CLOCK_SKEW_SECONDS="0"):
            with self.assertRaises(HTTPException) as raised:
                self.authenticate(self.token(iat=now + timedelta(seconds=5)))
            self.assertEqual(raised.exception.status_code, 401)

        with self.environment(UCC_JWT_CLOCK_SKEW_SECONDS="300"):
            principal = self.authenticate(self.token(iat=now + timedelta(seconds=240)))
            self.assertEqual(principal.subject, "doctor-1")

    def test_invalid_clock_skew_configuration_fails_closed(self):
        for value in ("invalid", "-1", "301"):
            with self.subTest(value=value):
                with self.environment(UCC_JWT_CLOCK_SKEW_SECONDS=value):
                    with self.assertRaises(HTTPException) as raised:
                        self.authenticate(self.token())
                self.assertEqual(raised.exception.status_code, 503)

    async def test_verified_principal_reaches_a_sync_route_and_is_then_cleared(self):
        app = FastAPI()

        @app.get("/doctor")
        def doctor_route(
            _authorized=Depends(require_scopes("consultation:read")),
        ):
            time.sleep(0.02)
            principal = current_ucc_principal()
            return {"subject": principal.subject if principal else None}

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        with self.environment():
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                responses = await asyncio.gather(
                    client.get(
                        "/doctor",
                        headers={"Authorization": f"Bearer {self.token(sub='doctor-1')}"},
                    ),
                    client.get(
                        "/doctor",
                        headers={"Authorization": f"Bearer {self.token(sub='doctor-2')}"},
                    ),
                )

        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertEqual(
            {response.json()["subject"] for response in responses},
            {"doctor-1", "doctor-2"},
        )
        self.assertIsNone(current_ucc_principal())
