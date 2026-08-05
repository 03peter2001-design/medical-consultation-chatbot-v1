"""LLM-assisted Safety draft editing without persistence side effects."""

from __future__ import annotations

import json
from typing import Any

from .read_model import draft_rule_groups
from .validation import candidate_document


def model_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("規則微調助理未回傳 JSON") from None
        try:
            payload = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as error:
            raise ValueError("規則微調助理回傳的 JSON 格式錯誤") from error
    if not isinstance(payload, dict):
        raise ValueError("規則微調助理回傳內容必須是物件")
    return payload


def suggest_safety_rule_edits(
    *,
    current: dict[str, Any],
    llm_client: Any,
    message: str,
    selected_labels: Any,
    groups: Any,
    history: Any,
) -> dict[str, Any]:
    """Return a validated draft; this function never persists rule changes."""
    normalized_message = message.strip()
    if not normalized_message or len(normalized_message) > 1000:
        raise ValueError("微調訊息必須是 1 至 1000 字")
    if (
        not isinstance(selected_labels, list)
        or not 1 <= len(selected_labels) <= 5
        or any(not isinstance(item, str) for item in selected_labels)
    ):
        raise ValueError("每次請勾選 1 至 5 個 Safety 標籤")

    draft = candidate_document(current, groups)
    draft_groups = draft_rule_groups(draft, current)
    by_original = {group["original_label"]: group for group in draft_groups}
    selected = list(dict.fromkeys(item.strip() for item in selected_labels))
    if len(selected) != len(selected_labels) or any(item not in by_original for item in selected):
        raise ValueError("勾選的 Safety 標籤不正確或重複")

    normalized_history = []
    if isinstance(history, list):
        for item in history[-6:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = str(item.get("content") or "").strip()[:1000]
            if role in {"user", "assistant"} and content:
                normalized_history.append({"role": role, "content": content})

    selected_groups = [by_original[label] for label in selected]
    prompt_payload = {
        "request": normalized_message,
        "conversation": normalized_history,
        "allowed_fact_codes": current["finding_codes"],
        "selected_safety_groups": selected_groups,
    }
    response = llm_client.generate_text(
        [
            {
                "role": "system",
                "content": (
                    "你是醫師端 Safety JSON 編輯助理。你只能修改提供的既有群組，"
                    "不得新增、刪除或改寫 rule code、kind、scope、route、level，"
                    "不得使用 allowed_fact_codes 以外的 fact。請依醫師要求提出草稿，"
                    "不要宣稱已儲存。回傳 JSON："
                    '{"reply":"簡短說明","safety_groups":[完整群組物件]}。'
                ),
            },
            {
                "role": "user",
                "content": json.dumps(prompt_payload, ensure_ascii=False),
            },
        ],
        temperature=0,
        max_tokens=4000,
    )
    payload = model_json(response)
    reply = str(payload.get("reply") or "").strip()[:1000]
    suggestions = payload.get("safety_groups")
    if not reply or not isinstance(suggestions, list):
        raise ValueError("規則微調助理缺少 reply 或 safety_groups")

    suggested_by_original: dict[str, dict[str, Any]] = {}
    for item in suggestions:
        if not isinstance(item, dict):
            raise ValueError("規則微調助理的 safety_groups 含非物件")
        original = str(item.get("original_label") or "").strip()
        if original not in selected or original in suggested_by_original:
            raise ValueError("規則微調助理修改了未勾選或重複的標籤")
        suggested_by_original[original] = item
    if set(suggested_by_original) != set(selected):
        raise ValueError("規則微調助理未完整回傳所有勾選標籤")

    merged_groups = [
        suggested_by_original.get(group["original_label"], group) for group in draft_groups
    ]
    validated = candidate_document(current, merged_groups)
    return {
        "reply": reply,
        "safety_groups": draft_rule_groups(validated, current),
        "saved": False,
    }
