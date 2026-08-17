import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main


class AvatarApiRequestTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    async def _run_inline(function, *args):
        return function(*args)

    async def test_warmup_forwards_override_and_omitted_default(self):
        calls = []

        class FakeEngine:
            def warmup(self, animation_enabled=None):
                calls.append(animation_enabled)
                return {"animation_enabled": animation_enabled}

        original_engine = main.engine
        main.engine = FakeEngine()
        try:
            with patch.object(main, "run_in_threadpool", self._run_inline):
                overridden = await main.warmup(
                    main.WarmupRequest(animation_enabled=False)
                )
                inherited = await main.warmup(None)
        finally:
            main.engine = original_engine

        self.assertEqual(overridden, {"animation_enabled": False})
        self.assertEqual(inherited, {"animation_enabled": None})
        self.assertEqual(calls, [False, None])

    async def test_synthesize_forwards_request_animation_override(self):
        calls = []

        class FakeEngine:
            def render(self, text, language, animation_enabled=None):
                calls.append((text, language, animation_enabled))
                return video_path, False, "static-image mode"

        original_engine = main.engine
        with tempfile.TemporaryDirectory() as directory:
            video_path = Path(directory) / "avatar.mp4"
            video_path.write_bytes(b"mp4")
            main.engine = FakeEngine()
            try:
                with patch.object(main, "run_in_threadpool", self._run_inline):
                    response = await main.synthesize(
                        main.SynthesisRequest(
                            text="您好",
                            language="mandarin",
                            animation_enabled=False,
                        )
                    )
            finally:
                main.engine = original_engine

        self.assertEqual(calls, [("您好", "mandarin", False)])
        self.assertEqual(response.headers["x-animation-model"], "static-image mode")


if __name__ == "__main__":
    unittest.main()
