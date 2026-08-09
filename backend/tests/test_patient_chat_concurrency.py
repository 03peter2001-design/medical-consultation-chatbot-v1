import asyncio
import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks

from app.models import ChatRequest
from app.routes import patient


class PatientChatConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_interview_requests_are_serialized(self):
        active = 0
        maximum = 0

        async def fake_chat(_request, _background_tasks, _patient_session):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.02)
            active -= 1
            return {"ok": True}

        with (
            patch.object(patient, "current_patient_session", return_value=None),
            patch.object(patient, "_chat_serialized", side_effect=fake_chat),
        ):
            await asyncio.gather(
                patient.chat(ChatRequest(message="一", session_id="same"), BackgroundTasks()),
                patient.chat(ChatRequest(message="二", session_id="same"), BackgroundTasks()),
            )

        self.assertEqual(maximum, 1)
