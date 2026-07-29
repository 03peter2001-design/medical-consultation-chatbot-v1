"""Add reviewable SNOMED CT suggestions to uncoded differential diagnoses."""

from __future__ import annotations

import json
import re
from typing import Any

SNOMED_CT_SYSTEM = "http://snomed.info/sct"
_coding_cache: dict[str, dict[str, str]] = {}


def _parse_json(text: str) -> Any:
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        text.strip(),
        flags=re.IGNORECASE,
    ).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = min(
            (index for index in (cleaned.find("["), cleaned.find("{")) if index >= 0),
            default=-1,
        )
        end = max(cleaned.rfind("]"), cleaned.rfind("}"))
        if start < 0 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def _valid_coding(
    value: Any,
    *,
    force_source: str | None = None,
) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    code = str(value.get("code", "")).strip()
    display = str(value.get("display", "")).strip()
    if (
        value.get("system") != SNOMED_CT_SYSTEM
        or not code.isdigit()
        or not 6 <= len(code) <= 18
        or not display
    ):
        return None
    source = force_source or str(value.get("source", "")).strip()
    if source not in {"fhir", "twcore-package", "ai-suggested"}:
        source = "ai-suggested"
    return {
        "system": SNOMED_CT_SYSTEM,
        "code": code,
        "display": display[:200],
        "source": source,
    }


def suggest_missing_differential_codings(
    hypotheses: list[dict[str, Any]] | None,
    llm_client: Any,
) -> list[dict[str, Any]]:
    """Return copied hypotheses with missing Coding suggestions when available."""
    result = [dict(item) for item in (hypotheses or []) if isinstance(item, dict)]
    missing = list(
        dict.fromkeys(
            str(item.get("condition", "")).strip()[:200]
            for item in result
            if item.get("condition") and not _valid_coding(item.get("coding"))
        )
    )
    uncached = [condition for condition in missing if condition not in _coding_cache]
    if uncached:
        try:
            response = llm_client.generate_text(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是SNOMED CT術語編碼助手。只處理疾病名稱，不會收到病人資料。"
                            "為每個輸入名稱提供最符合的SNOMED CT概念。只能輸出JSON陣列；"
                            "不得新增、刪除或改寫condition。若無法可靠編碼，coding填null。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"疾病名稱：{json.dumps(uncached, ensure_ascii=False)}\n"
                            "輸出格式："
                            '[{"condition":"原字串","coding":'
                            '{"system":"http://snomed.info/sct",'
                            '"code":"純數字概念ID","display":"正式英文名稱"}}]'
                        ),
                    },
                ],
                temperature=0,
                max_tokens=600,
            )
            payload = _parse_json(response)
            items = payload if isinstance(payload, list) else payload.get("items", [])
            requested = set(uncached)
            for item in items:
                if not isinstance(item, dict):
                    continue
                condition = str(item.get("condition", "")).strip()
                coding = _valid_coding(
                    item.get("coding"),
                    force_source="ai-suggested",
                )
                if condition in requested and coding:
                    _coding_cache[condition] = coding
        except Exception:
            pass

    for hypothesis in result:
        condition = str(hypothesis.get("condition", "")).strip()
        explicit = _valid_coding(hypothesis.get("coding"))
        hypothesis["coding"] = explicit or _coding_cache.get(condition)
    return result
