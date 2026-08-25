"""Shared prompt request and message-building primitives."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromptRequest:
    """One model task with an explicit message list and token budget."""

    task: str
    messages: list[dict[str, str]]
    max_tokens: int
    title: str | None = None


def json_prompt_messages(
    system_prompt: str,
    payload: dict[str, Any],
) -> list[dict[str, str]]:
    """Render the repository's standard system + compact JSON prompt format."""

    return [
        {"role": "system", "content": system_prompt.strip()},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def text_prompt_messages(system_prompt: str, user_prompt: str) -> list[dict[str, str]]:
    """Render the standard two-message format for a free-text prompt."""

    return [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt.strip()},
    ]
