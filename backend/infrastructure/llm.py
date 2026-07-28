"""LLM provider abstraction for Groq and the Gemini Developer API."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

SUPPORTED_PROVIDERS = {"groq", "gemini"}
DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "gemini": "gemini-2.5-flash",
}


def _bounded_int(
    value: str | None,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def gemini_generation_limits(
    model: str,
    requested_output_tokens: int,
    env: Mapping[str, str] | None = None,
) -> tuple[int, int | None]:
    """回傳包含 thinking tokens 的 API 上限，以及 thinking budget。"""
    values = os.environ if env is None else env
    requested = max(1, int(requested_output_tokens))
    configured = values.get("GEMINI_THINKING_BUDGET")

    if model.startswith("gemini-2.5-pro"):
        budget = _bounded_int(
            configured,
            default=128,
            minimum=128,
            maximum=32768,
        )
        return min(65536, requested + budget), budget
    if model.startswith("gemini-2.5-flash"):
        budget = _bounded_int(
            configured,
            default=0,
            minimum=0,
            maximum=24576,
        )
        return min(65536, requested + budget), budget
    return max(requested, 256), None


def _finish_reason(response: Any) -> str:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return "UNKNOWN"
    reason = getattr(candidates[0], "finish_reason", None)
    value = getattr(reason, "value", None)
    return str(value or reason or "UNKNOWN").split(".")[-1]


def resolve_provider(env: Mapping[str, str] | None = None) -> str:
    """Resolve the configured provider while keeping Groq as the legacy default."""
    values = os.environ if env is None else env
    configured = values.get("LLM_PROVIDER", "").strip().lower()

    if configured:
        if configured not in SUPPORTED_PROVIDERS:
            choices = "、".join(sorted(SUPPORTED_PROVIDERS))
            raise RuntimeError(f"不支援的 LLM_PROVIDER：{configured}（可用值：{choices}）")
        return configured

    if values.get("GROQ_API_KEY", "").strip():
        return "groq"
    if values.get("GEMINI_API_KEY", "").strip():
        return "gemini"

    raise RuntimeError(
        "缺少模型 API Key：請設定 GROQ_API_KEY 或 GEMINI_API_KEY；"
        "也可用 LLM_PROVIDER 指定 groq／gemini"
    )


class LLMClient:
    """Expose the text-generation and transcription operations used by the app."""

    def __init__(self, env: Mapping[str, str] | None = None):
        self._env = os.environ if env is None else env
        self.provider = resolve_provider(self._env)
        configured_model = self._env.get(f"{self.provider.upper()}_MODEL", "").strip()
        self.model = configured_model or DEFAULT_MODELS[self.provider]
        self._client = self._build_client()

    def _build_client(self) -> Any:
        if self.provider == "groq":
            api_key = self._env.get("GROQ_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("LLM_PROVIDER=groq，但缺少環境變數 GROQ_API_KEY")
            try:
                from groq import Groq
            except ImportError as exc:
                raise RuntimeError("缺少 groq 套件，請重新安裝 backend/requirements.txt") from exc
            return Groq(api_key=api_key)

        api_key = self._env.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("LLM_PROVIDER=gemini，但缺少環境變數 GEMINI_API_KEY")
        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError(
                "缺少 google-genai 套件，請重新安裝 backend/requirements.txt"
            ) from exc
        return genai.Client(api_key=api_key)

    def generate_text(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> str:
        if self.provider == "groq":
            response = self._client.chat.completions.create(
                model=self.model,
                messages=list(messages),
                temperature=temperature,
                max_tokens=max_tokens,
            )
            text = response.choices[0].message.content
        else:
            text = self._generate_gemini_text(messages, temperature, max_tokens)

        if not text or not str(text).strip():
            raise RuntimeError(f"{self.provider} 未回傳文字內容")
        return str(text).strip()

    def _generate_gemini_text(
        self,
        messages: Sequence[Mapping[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str | None:
        from google.genai import types

        system_parts: list[str] = []
        contents: list[Any] = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            if role == "system":
                system_parts.append(content)
                continue
            contents.append(
                types.Content(
                    role="model" if role == "assistant" else "user",
                    parts=[types.Part.from_text(text=content)],
                )
            )

        effective_max_tokens, thinking_budget = gemini_generation_limits(
            self.model,
            max_tokens,
            self._env,
        )
        config_kwargs: dict[str, Any] = {
            "system_instruction": "\n\n".join(system_parts) or None,
            "temperature": temperature,
            "max_output_tokens": effective_max_tokens,
        }
        if thinking_budget is not None:
            # Gemini 2.5 的 thinking tokens 會計入 max_output_tokens。
            # Flash 預設關閉；Pro 無法關閉，因此使用官方最小值 128。
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)

        def generate(output_limit: int):
            request_config = {
                **config_kwargs,
                "max_output_tokens": output_limit,
            }
            return self._client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(**request_config),
            )

        response = generate(effective_max_tokens)
        text = response.text
        reason = _finish_reason(response)
        if (not text or not text.strip()) and reason == "MAX_TOKENS":
            # 防止模型仍因動態輸出或 SDK 行為耗盡上限；只重試一次，
            # 且不記錄 prompt。
            retry_limit = min(
                65536,
                max(effective_max_tokens * 2, effective_max_tokens + 512),
            )
            response = generate(retry_limit)
            text = response.text
            reason = _finish_reason(response)

        if not text or not text.strip():
            raise RuntimeError(f"gemini 未回傳文字內容（finish_reason={reason}）")
        return text

    def transcribe(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        mime_type: str,
        prompt: str,
    ) -> str:
        if self.provider == "groq":
            model = self._env.get("GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3-turbo").strip()
            transcription = self._client.audio.transcriptions.create(
                file=(filename, audio_bytes),
                model=model,
                language="zh",
                response_format="text",
                prompt=prompt,
            )
            return str(transcription).strip()

        from google.genai import types

        normalized_mime = (mime_type or "audio/webm").split(";", 1)[0].strip()
        transcription_prompt = (
            f"{prompt}\n"
            "請將這段音訊逐字轉錄成繁體中文。只輸出轉錄文字，不要摘要、解釋、"
            "Markdown 或加上說話者標籤。聽不清楚時不要自行補寫醫療資訊。"
        )
        transcription_config: dict[str, Any] = {
            "temperature": 0,
            "max_output_tokens": 1000,
        }
        if self.model.startswith("gemini-2.5-flash"):
            transcription_config["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

        response = self._client.models.generate_content(
            model=self.model,
            contents=[
                transcription_prompt,
                types.Part.from_bytes(data=audio_bytes, mime_type=normalized_mime),
            ],
            config=types.GenerateContentConfig(**transcription_config),
        )
        if not response.text or not response.text.strip():
            raise RuntimeError("gemini 未回傳語音轉錄文字")
        return response.text.strip()
