"""Client for the private, locally hosted speech and talking-head service."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AvatarUnavailableError(RuntimeError):
    """Raised when the optional local avatar service cannot serve a request."""


@dataclass(frozen=True)
class AvatarVideo:
    content: bytes
    content_type: str
    speech_model: str
    animation_model: str
    cache_hit: bool


class AvatarClient:
    """Small stdlib HTTP client; the service is reachable on Docker's private network."""

    def __init__(self, env: dict[str, str] | None = None):
        source = env if env is not None else os.environ
        self.enabled = source.get("AVATAR_ENABLED", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.base_url = source.get(
            "AVATAR_SERVICE_URL",
            "http://avatar:8090",
        ).strip().rstrip("/")
        self.timeout = max(
            10.0,
            float(source.get("AVATAR_TIMEOUT_SECONDS", "600")),
        )
        self.max_video_bytes = max(
            1,
            int(source.get("AVATAR_MAX_VIDEO_MB", "80")),
        ) * 1024 * 1024

    def configured_status(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "available": False,
            "speech_model": "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
            "animation_model": "TMElyralab/MuseTalk 1.5",
            "device": "unknown",
        }

    def status(self) -> dict[str, object]:
        fallback = self.configured_status()
        if not self.enabled:
            return fallback
        try:
            request = Request(f"{self.base_url}/health", method="GET")
            with urlopen(request, timeout=min(self.timeout, 5.0)) as response:
                payload = json.loads(response.read(64 * 1024).decode("utf-8"))
                if not isinstance(payload, dict):
                    return fallback
        except (HTTPError, URLError, TimeoutError, socket.timeout, ValueError):
            return fallback
        return {
            **fallback,
            "available": payload.get("status") == "ok",
            "speech_model": str(payload.get("speech_model") or fallback["speech_model"]),
            "animation_model": str(
                payload.get("animation_model") or fallback["animation_model"]
            ),
            "device": str(payload.get("device") or "unknown"),
        }

    def render(self, text: str) -> AvatarVideo:
        if not self.enabled:
            raise AvatarUnavailableError("本地 Avatar 服務未啟用")
        body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.base_url}/v1/synthesize",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                content = response.read(self.max_video_bytes + 1)
                if len(content) > self.max_video_bytes:
                    raise AvatarUnavailableError("Avatar 影片超過允許的大小")
                content_type = response.headers.get_content_type()
                if not content or content_type != "video/mp4":
                    raise AvatarUnavailableError("Avatar 服務未回傳有效的 MP4 影片")
                return AvatarVideo(
                    content=content,
                    content_type=content_type,
                    speech_model=response.headers.get(
                        "X-Speech-Model",
                        "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
                    ),
                    animation_model=response.headers.get(
                        "X-Animation-Model",
                        "TMElyralab/MuseTalk 1.5",
                    ),
                    cache_hit=response.headers.get("X-Avatar-Cache") == "hit",
                )
        except HTTPError as error:
            try:
                detail = json.loads(error.read(64 * 1024)).get("detail", "")
            except (ValueError, AttributeError):
                detail = ""
            raise AvatarUnavailableError(detail or "本地 Avatar 產生失敗") from error
        except (URLError, TimeoutError, socket.timeout) as error:
            raise AvatarUnavailableError("本地 Avatar 服務無法連線或逾時") from error
