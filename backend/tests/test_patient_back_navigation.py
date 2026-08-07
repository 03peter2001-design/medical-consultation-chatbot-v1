import asyncio
import os
import time
import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks

os.environ.setdefault("GROQ_API_KEY", "test-only-not-a-real-key")

from app.models import ChatRequest
from app.routes import patient
from domain.questionnaires import build_questionnaire


class PatientBackNavigationTests(unittest.TestCase):
    def test_legacy_interview_restores_previous_question_and_answer_state(self):
        session_id = "patient-back-test"
        isolated_sessions = {
            session_id: {
                "session_id": session_id,
                "engine": "legacy",
                "step": 1,
                "index": 1,
                "questionnaire": build_questionnaire("chest"),
                "data": {"type": "chest", "types": ["chest"]},
                "prefilled_fields": [],
                "_history": [],
                "ts": time.time(),
            }
        }

        with (
            patch.object(patient, "INTERVIEW_ENGINE", "legacy"),
            patch.object(patient, "sessions", isolated_sessions),
        ):
            answered = asyncio.run(
                patient._chat_impl(
                    ChatRequest(
                        session_id=session_id,
                        message="測試病人",
                    ),
                    BackgroundTasks(),
                )
            )
            restored = asyncio.run(
                patient._chat_impl(
                    ChatRequest(session_id=session_id, action="back"),
                    BackgroundTasks(),
                )
            )

        self.assertTrue(answered["can_go_back"])
        self.assertEqual(answered["question_input"]["field"], "gender")
        self.assertEqual(restored["question_input"]["field"], "name")
        self.assertFalse(restored["can_go_back"])
        self.assertNotIn("name", isolated_sessions[session_id]["data"])


if __name__ == "__main__":
    unittest.main()
