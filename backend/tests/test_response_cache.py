import unittest

import httpx
from fastapi import FastAPI, HTTPException

from app.response_cache import prevent_api_response_caching


class ResponseCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = FastAPI()
        app.middleware("http")(prevent_api_response_caching)

        @app.get("/ok")
        async def ok():
            return {"status": "ok"}

        @app.get("/unauthorized")
        async def unauthorized():
            raise HTTPException(status_code=401, detail="authentication required")

        self.transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async def request(self, path: str):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            return await client.get(path)

    async def test_success_and_authentication_failure_are_not_cacheable(self):
        for path, expected_status in (("/ok", 200), ("/unauthorized", 401)):
            with self.subTest(path=path):
                response = await self.request(path)
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(response.headers["pragma"], "no-cache")
