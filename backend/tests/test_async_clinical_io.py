import asyncio
import threading
import time
import unittest

import httpx
from fastapi import FastAPI

from app.services.async_clinical_io import (
    CLINICAL_IO_CONCURRENCY,
    ClinicalOperationTimeout,
    run_clinical_io,
)


class AsyncClinicalIoTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_sync_call_does_not_block_event_loop(self):
        ticked = asyncio.Event()

        async def ticker():
            await asyncio.sleep(0.01)
            ticked.set()

        slow = asyncio.create_task(run_clinical_io(time.sleep, 0.08))
        await ticker()
        self.assertTrue(ticked.is_set())
        await slow

    async def test_timeout_is_stable_and_does_not_expose_provider_error(self):
        with self.assertRaisesRegex(ClinicalOperationTimeout, "timed out"):
            await run_clinical_io(time.sleep, 0.08, timeout_seconds=0.01)

    async def test_unrelated_health_endpoint_responds_during_slow_call(self):
        app = FastAPI()

        @app.get("/slow")
        async def slow():
            await run_clinical_io(time.sleep, 0.08)
            return {"status": "done"}

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            slow_request = asyncio.create_task(client.get("/slow"))
            await asyncio.sleep(0.01)
            started = asyncio.get_running_loop().time()
            response = await client.get("/health")
            elapsed = asyncio.get_running_loop().time() - started
            self.assertEqual(response.json(), {"status": "ok"})
            self.assertLess(elapsed, 0.05)
            self.assertEqual((await slow_request).status_code, 200)

    async def test_parallel_calls_respect_configured_capacity(self):
        lock = threading.Lock()
        active = 0
        maximum = 0

        def measured_call():
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.03)
            with lock:
                active -= 1

        await asyncio.gather(
            *(run_clinical_io(measured_call) for _ in range(CLINICAL_IO_CONCURRENCY + 3))
        )
        self.assertLessEqual(maximum, CLINICAL_IO_CONCURRENCY)
