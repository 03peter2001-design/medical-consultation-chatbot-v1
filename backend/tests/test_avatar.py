import asyncio
import json
import unittest
from email.message import Message
from unittest.mock import AsyncMock, patch

from app.contracts import AvatarSpeechRequest, AvatarStatusResponse
from infrastructure.avatar import AvatarClient, AvatarUnavailableError, AvatarVideo


class _Response:
    def __init__(self, body: bytes, content_type: str = "application/json"):
        self._body = body
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["X-Speech-Model"] = "cosy-test"
        self.headers["X-Animation-Model"] = "muse-test"
        self.headers["X-Avatar-Cache"] = "hit"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=None):
        return self._body


class AvatarClientTests(unittest.TestCase):
    def test_speech_request_trims_and_rejects_blank_text(self):
        request = AvatarSpeechRequest(text="  您好  ")
        self.assertEqual(request.text, "您好")
        self.assertEqual(request.language, "mandarin")
        self.assertEqual(
            AvatarSpeechRequest(text="您好", language="minnan").language,
            "minnan",
        )
        with self.assertRaisesRegex(ValueError, "must not be blank"):
            AvatarSpeechRequest(text="  \n ")
        with self.assertRaises(ValueError):
            AvatarSpeechRequest(text="您好", language="english")

    def test_disabled_client_does_not_call_network(self):
        client = AvatarClient({"AVATAR_ENABLED": "false"})
        with patch("infrastructure.avatar.urlopen") as urlopen:
            with self.assertRaisesRegex(AvatarUnavailableError, "未啟用"):
                client.render("您好")
        urlopen.assert_not_called()

    def test_status_reports_private_service_metadata(self):
        client = AvatarClient({"AVATAR_ENABLED": "true"})
        body = json.dumps(
            {
                "status": "ok",
                "speech_model": "cosy-test",
                "animation_model": "muse-test",
                "device": "cuda:0",
            }
        ).encode()
        with patch("infrastructure.avatar.urlopen", return_value=_Response(body)):
            status = client.status()
        self.assertTrue(status["enabled"])
        self.assertTrue(status["available"])
        self.assertEqual(status["device"], "cuda:0")
        self.assertTrue(status["animation_enabled"])
        self.assertEqual(status["animation_model"], "muse-test")

    def test_status_uses_backend_static_mode_when_service_default_differs(self):
        client = AvatarClient(
            {
                "AVATAR_ENABLED": "true",
                "AVATAR_ANIMATION_ENABLED": "false",
            }
        )
        body = json.dumps(
            {
                "status": "ok",
                "speech_model": "cosy-test",
                "animation_model": "muse-test",
                "animation_enabled": True,
                "device": "cuda:0",
                "speech_loaded": True,
                "animation_loaded": False,
            }
        ).encode()
        with patch("infrastructure.avatar.urlopen", return_value=_Response(body)):
            status = client.status()

        browser_status = AvatarStatusResponse.model_validate(status).model_dump()
        self.assertFalse(browser_status["animation_enabled"])
        self.assertEqual(browser_status["animation_model"], "static-image mode")
        self.assertTrue(browser_status["loaded"])

    def test_render_preserves_model_and_cache_headers(self):
        client = AvatarClient({"AVATAR_ENABLED": "true", "AVATAR_MAX_VIDEO_MB": "1"})
        request_body = {}

        def respond(request, timeout):
            request_body.update(json.loads(request.data.decode("utf-8")))
            return _Response(b"video", "video/mp4")

        with patch(
            "infrastructure.avatar.urlopen",
            side_effect=respond,
        ):
            result = client.render("請問哪裡不舒服？", "minnan")
        self.assertEqual(result.content, b"video")
        self.assertEqual(result.content_type, "video/mp4")
        self.assertEqual(result.speech_model, "cosy-test")
        self.assertEqual(result.animation_model, "muse-test")
        self.assertTrue(result.cache_hit)
        self.assertEqual(request_body["language"], "minnan")
        self.assertTrue(request_body["animation_enabled"])

    def test_warmup_requires_all_private_avatar_models(self):
        client = AvatarClient({"AVATAR_ENABLED": "true"})
        body = json.dumps(
            {
                "status": "ok",
                "speech_model": "cosy-test",
                "animation_model": "muse-test",
                "device": "cuda:0",
                "speech_loaded": True,
                "animation_loaded": True,
            }
        ).encode()
        with patch("infrastructure.avatar.urlopen", return_value=_Response(body)) as call:
            status = client.warmup()

        self.assertTrue(status["available"])
        self.assertTrue(status["loaded"])
        self.assertEqual(call.call_args.args[0].method, "POST")
        self.assertTrue(call.call_args.args[0].full_url.endswith("/v1/warmup"))
        self.assertTrue(json.loads(call.call_args.args[0].data.decode())["animation_enabled"])

    def test_warmup_accepts_speech_only_static_avatar_mode(self):
        client = AvatarClient(
            {
                "AVATAR_ENABLED": "true",
                "AVATAR_ANIMATION_ENABLED": "false",
            }
        )
        body = json.dumps(
            {
                "status": "ok",
                "speech_model": "cosy-test",
                "animation_model": "static-image mode",
                "animation_enabled": False,
                "device": "cuda:0",
                "speech_loaded": True,
                "animation_loaded": False,
            }
        ).encode()
        with patch(
            "infrastructure.avatar.urlopen",
            return_value=_Response(body),
        ) as call:
            status = client.warmup()

        self.assertTrue(status["available"])
        self.assertTrue(status["loaded"])
        self.assertFalse(status["animation_enabled"])
        self.assertEqual(status["animation_model"], "static-image mode")
        self.assertFalse(json.loads(call.call_args.args[0].data.decode())["animation_enabled"])

    def test_render_sends_backend_static_mode_to_avatar_service(self):
        client = AvatarClient(
            {
                "AVATAR_ENABLED": "true",
                "AVATAR_ANIMATION_ENABLED": "off",
            }
        )
        request_body = {}

        def respond(request, timeout):
            request_body.update(json.loads(request.data.decode("utf-8")))
            return _Response(b"video", "video/mp4")

        with patch("infrastructure.avatar.urlopen", side_effect=respond):
            client.render("您好")

        self.assertFalse(request_body["animation_enabled"])

    def test_render_rejects_non_video_success_response(self):
        client = AvatarClient({"AVATAR_ENABLED": "true"})
        with patch(
            "infrastructure.avatar.urlopen",
            return_value=_Response(b'{"status":"ok"}', "application/json"),
        ):
            with self.assertRaisesRegex(AvatarUnavailableError, "MP4"):
                client.render("請問哪裡不舒服？")

    def test_status_rejects_non_object_json(self):
        client = AvatarClient({"AVATAR_ENABLED": "true"})
        with patch(
            "infrastructure.avatar.urlopen",
            return_value=_Response(b"[]"),
        ):
            status = client.status()
        self.assertTrue(status["enabled"])
        self.assertFalse(status["available"])

    def test_speak_route_returns_private_mp4(self):
        async def exercise_route():
            from app.routes.system import avatar_speak

            video = AvatarVideo(
                content=b"mp4-test",
                content_type="video/mp4",
                speech_model="cosy-test",
                animation_model="muse-test",
                cache_hit=True,
            )
            threadpool = AsyncMock(return_value=video)
            with patch(
                "app.routes.system.run_in_threadpool",
                new=threadpool,
            ):
                response = await avatar_speak(AvatarSpeechRequest(text=" 您好 ", language="minnan"))

            return response, threadpool

        response, threadpool = asyncio.run(exercise_route())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "video/mp4")
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(response.headers["x-avatar-cache"], "hit")
        self.assertEqual(response.body, b"mp4-test")
        self.assertEqual(threadpool.await_args.args[2], "minnan")


if __name__ == "__main__":
    unittest.main()
