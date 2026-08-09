import unittest

import httpx
from fastapi import APIRouter, FastAPI, HTTPException

from app.errors import install_error_handlers


class ErrorBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        app = FastAPI()
        install_error_handlers(app)
        router = APIRouter()

        @router.get("/http-error")
        async def http_error():
            raise HTTPException(status_code=503, detail="safe public message")

        @router.get("/internal-error")
        async def internal_error():
            raise RuntimeError("postgresql://secret-user:secret-password@internal-db/patient")

        @router.get("/validated/{identifier}")
        async def validated(identifier: int):
            return {"identifier": identifier}

        app.include_router(router)
        self.transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    def assert_stable_error(self, response, code):
        payload = response.json()
        self.assertEqual(payload["error_code"], code)
        self.assertRegex(payload["correlation_id"], r"^[0-9a-f]{24}$")
        self.assertEqual(response.headers["x-error-code"], code)
        self.assertEqual(
            response.headers["x-correlation-id"],
            payload["correlation_id"],
        )

    async def request(self, path):
        async with httpx.AsyncClient(
            transport=self.transport,
            base_url="http://test",
        ) as client:
            return await client.get(path)

    async def test_http_errors_keep_safe_detail_and_add_tracking_fields(self):
        response = await self.request("/http-error")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "safe public message")
        self.assert_stable_error(response, "HTTP_503")

    async def test_unhandled_exception_text_is_not_returned(self):
        response = await self.request("/internal-error")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret-password", response.text)
        self.assertNotIn("internal-db", response.text)
        self.assert_stable_error(response, "INTERNAL_SERVER_ERROR")

    async def test_validation_errors_do_not_reflect_rejected_input(self):
        rejected = "synthetic-secret-patient-answer"
        response = await self.request(f"/validated/{rejected}")
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(rejected, response.text)
        self.assertNotIn('"input"', response.text)
        self.assert_stable_error(response, "REQUEST_VALIDATION_FAILED")
