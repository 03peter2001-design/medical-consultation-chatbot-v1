"""Gemini 查詢翻譯層：去識別化、結構化輸出與安全 fallback。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Mapping

LOGGER = logging.getLogger("rag.translation")
SUPPORTED_TRANSLATORS = {"off", "gemini"}
SUPPORTED_QUERY_MODES = {"dual", "english"}

_TAIWAN_ID_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z][12]\d{8}(?!\d)", re.IGNORECASE)
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_MOBILE_RE = re.compile(r"(?<!\d)(?:\+?886[-\s]?)?0?9\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)")
_LANDLINE_RE = re.compile(r"(?<!\d)(?:\+?886[-\s]?)?0\d[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)")
_LABELED_SECRET_RE = re.compile(
    r"(?P<label>身分證(?:字號)?|身份證(?:字號)?|病歷號|"
    r"medical\s*record(?:\s*number)?|mrn)"
    r"\s*[:：#]?\s*[A-Za-z0-9-]{4,}",
    re.IGNORECASE,
)
_LABELED_TEXT_RE = re.compile(
    r"(?P<label>姓名|name|地址|address)"
    r"\s*[:：]\s*[^,，;；\n]{1,80}",
    re.IGNORECASE,
)
_SPOKEN_NAME_RE = re.compile(
    r"(?P<prefix>我叫|我是)\s*[\u3400-\u9fff]{2,4}"
    r"(?=[,，。；;\s])"
)


def _configured_value(
    env: Mapping[str, str],
    key: str,
    default: str,
    supported: set[str],
) -> str:
    value = env.get(key, default).strip().lower()
    if value not in supported:
        LOGGER.warning(
            "Unsupported RAG translation setting key=%s; using %s",
            key,
            default,
        )
        return default
    return value


def redact_sensitive_text(text: str) -> str:
    """遮蔽常見直接識別資訊；回傳內容不得寫入日誌。"""
    redacted = str(text or "")
    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", redacted)
    redacted = _TAIWAN_ID_RE.sub("[REDACTED_ID]", redacted)
    redacted = _MOBILE_RE.sub("[REDACTED_PHONE]", redacted)
    redacted = _LANDLINE_RE.sub("[REDACTED_PHONE]", redacted)
    redacted = _LABELED_SECRET_RE.sub(
        lambda match: f"{match.group('label')}:[REDACTED_ID]",
        redacted,
    )
    redacted = _LABELED_TEXT_RE.sub(
        lambda match: f"{match.group('label')}:[REDACTED_TEXT]",
        redacted,
    )
    redacted = _SPOKEN_NAME_RE.sub(
        lambda match: f"{match.group('prefix')}[REDACTED_TEXT]",
        redacted,
    )
    return redacted


def contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text or ""))


@dataclass(frozen=True)
class QueryNormalization:
    literal_translation: str
    positive_findings: tuple[str, ...]
    negative_findings: tuple[str, ...]
    uncertain_findings: tuple[str, ...]
    temporality: tuple[str, ...]
    standardized_terms: tuple[str, ...]
    retrieval_query: str

    def english_search_text(self) -> str:
        parts = (
            self.retrieval_query,
            " ".join(self.standardized_terms),
            self.literal_translation,
        )
        return " ".join(dict.fromkeys(part.strip() for part in parts if part.strip()))


QUERY_NORMALIZATION_SCHEMA = {
    "type": "object",
    "properties": {
        "literal_translation": {
            "type": "string",
            "description": "Faithful English translation with negation preserved.",
        },
        "positive_findings": {
            "type": "array",
            "items": {"type": "string"},
        },
        "negative_findings": {
            "type": "array",
            "items": {"type": "string"},
        },
        "uncertain_findings": {
            "type": "array",
            "items": {"type": "string"},
        },
        "temporality": {
            "type": "array",
            "items": {"type": "string"},
        },
        "standardized_terms": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "English clinical terms directly equivalent to the input; never inferred diagnoses."
            ),
        },
        "retrieval_query": {
            "type": "string",
            "description": "Concise English literature retrieval query.",
        },
    },
    "required": [
        "literal_translation",
        "positive_findings",
        "negative_findings",
        "uncertain_findings",
        "temporality",
        "standardized_terms",
        "retrieval_query",
    ],
}

SYSTEM_INSTRUCTION = """
You are a medical retrieval query translator, not a diagnostician.
Translate Traditional Chinese patient or clinician text into faithful English
for searching an English medical knowledge base.

Rules:
1. Preserve every negation, uncertainty, onset, duration, location, laterality,
   severity, and temporal relationship.
2. Do not add symptoms, history, test findings, diagnoses, probabilities, or
   recommendations that are not explicitly present.
3. standardized_terms may contain only direct terminology equivalents of the
   source text. Do not generate a differential diagnosis.
4. Keep [REDACTED_*] placeholders unchanged and never reconstruct identity.
5. retrieval_query must retain negative and uncertain findings when clinically
   relevant. Return only the requested JSON object.
""".strip()


def _clean_string(value: Any, max_length: int = 1500) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:max_length].strip()


def _clean_string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    cleaned = []
    for item in value[:24]:
        text = _clean_string(item, 200)
        if text and text not in cleaned:
            cleaned.append(text)
    return tuple(cleaned)


def parse_normalization(payload: str | Mapping[str, Any]) -> QueryNormalization:
    data = json.loads(payload) if isinstance(payload, str) else dict(payload)
    if not isinstance(data, dict):
        raise ValueError("Gemini normalization output must be an object")

    required = set(QUERY_NORMALIZATION_SCHEMA["required"])
    if not required.issubset(data):
        raise ValueError("Gemini normalization output is missing fields")

    literal_translation = _clean_string(data["literal_translation"])
    retrieval_query = _clean_string(data["retrieval_query"])
    if not literal_translation or not retrieval_query:
        raise ValueError("Gemini normalization output has empty query text")
    if not re.search(r"[A-Za-z]", retrieval_query):
        raise ValueError("Gemini retrieval query is not English")

    return QueryNormalization(
        literal_translation=literal_translation,
        positive_findings=_clean_string_list(data["positive_findings"]),
        negative_findings=_clean_string_list(data["negative_findings"]),
        uncertain_findings=_clean_string_list(data["uncertain_findings"]),
        temporality=_clean_string_list(data["temporality"]),
        standardized_terms=_clean_string_list(data["standardized_terms"]),
        retrieval_query=retrieval_query,
    )


class GeminiQueryNormalizer:
    """Lazy Gemini normalizer with an identity-free, bounded in-memory cache."""

    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        client: Any | None = None,
    ):
        self.env = os.environ if env is None else env
        self.translator = _configured_value(
            self.env,
            "RAG_QUERY_TRANSLATION",
            "off",
            SUPPORTED_TRANSLATORS,
        )
        self.query_mode = _configured_value(
            self.env,
            "RAG_QUERY_MODE",
            "dual",
            SUPPORTED_QUERY_MODES,
        )
        self.model = self.env.get("GEMINI_TRANSLATION_MODEL", "").strip() or "gemini-2.5-flash"
        try:
            configured_max_chars = int(self.env.get("RAG_TRANSLATION_MAX_INPUT_CHARS", "4000"))
        except (TypeError, ValueError):
            configured_max_chars = 4000
        self.max_input_chars = max(
            200,
            min(configured_max_chars, 12000),
        )
        self._client = client
        self._cache: OrderedDict[str, QueryNormalization] = OrderedDict()
        self._cache_size = 256

    @property
    def enabled(self) -> bool:
        return self.translator == "gemini"

    @property
    def client(self):
        if self._client is None:
            api_key = self.env.get("GEMINI_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("RAG_QUERY_TRANSLATION=gemini but key is missing")
            from google import genai

            self._client = genai.Client(api_key=api_key)
        return self._client

    def normalize(self, query: str) -> QueryNormalization | None:
        if not self.enabled or not contains_cjk(query):
            return None

        redacted = redact_sensitive_text(query)[: self.max_input_chars].strip()
        if not redacted:
            return None
        cache_key = hashlib.sha256(redacted.encode("utf-8")).hexdigest()
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        try:
            from google.genai import types

            config_kwargs: dict[str, Any] = {
                "system_instruction": SYSTEM_INSTRUCTION,
                "temperature": 0,
                "max_output_tokens": 700,
                "response_mime_type": "application/json",
                "response_schema": QUERY_NORMALIZATION_SCHEMA,
            }
            if self.model.startswith("gemini-2.5-flash"):
                config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
            elif self.model.startswith("gemini-2.5-pro"):
                config_kwargs["max_output_tokens"] = 2048
                config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=128)
            response = self.client.models.generate_content(
                model=self.model,
                contents=redacted,
                config=types.GenerateContentConfig(**config_kwargs),
            )
            normalized = parse_normalization(response.text or "")
        except Exception as exc:
            # API 例外可能含 request 內容，因此只記錄例外類型。
            LOGGER.warning(
                "Gemini query normalization failed error_type=%s",
                type(exc).__name__,
            )
            return None

        self._cache[cache_key] = normalized
        self._cache.move_to_end(cache_key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return normalized


_normalizer: GeminiQueryNormalizer | None = None


def get_query_normalizer() -> GeminiQueryNormalizer:
    global _normalizer
    if _normalizer is None:
        _normalizer = GeminiQueryNormalizer()
    return _normalizer


def get_translation_status() -> dict[str, str | bool]:
    normalizer = get_query_normalizer()
    return {
        "enabled": normalizer.enabled,
        "provider": normalizer.translator,
        "query_mode": normalizer.query_mode,
        "model": normalizer.model if normalizer.enabled else "",
    }
