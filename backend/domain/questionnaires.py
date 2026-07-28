"""從分類 JSON 載入資料驅動的預問診問卷。"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from copy import deepcopy
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

QUESTIONNAIRE_DATA_DIR = Path(__file__).resolve().parents[1] / "questionnaire_data"
QUESTIONNAIRE_CATEGORIES = {
    "chief",
    "basic",
    "history",
    "chest",
    "headache",
    "abdomen",
}
DISEASE_ROUTES = ("chest", "headache", "abdomen")
ALLOWED_INPUT_KINDS = {"text", "choice", "date", "duration"}

SECTION_LABELS = {
    "chief": "主訴",
    "basic": "基本資料",
    "history": "病史",
    "disease": "症狀問卷",
}

ROUTE_LABELS = {
    "chest": "胸痛",
    "headache": "頭痛",
    "abdomen": "腹痛",
}

_QUESTION_DEFAULTS = {
    "options": [],
    "multiple": False,
    "allow_other": False,
    "other_label": "其他／補充說明",
    "exclusive_options": [],
    "quick_options": [],
    "units": [],
    "placeholder": "",
    "condition": None,
    "semantic_options": {},
}


def _validate_string_list(
    value: Any,
    *,
    category: str,
    field: str,
    key: str,
) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{category}.json 的 {field}.{key} 必須是非空字串陣列")
    return value


def _validate_question(
    raw: Any,
    *,
    category: str,
    section: str,
    position: int,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{category}.json questions[{position}] 必須是物件")

    item = {**_QUESTION_DEFAULTS, **raw, "section": section}
    field = item.get("field")
    prompt = item.get("prompt")
    kind = item.get("kind")
    if not isinstance(field, str) or not field.strip():
        raise ValueError(f"{category}.json questions[{position}] 缺少 field")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"{category}.json 的 {field} 缺少 prompt")
    if kind not in ALLOWED_INPUT_KINDS:
        raise ValueError(f"{category}.json 的 {field}.kind 不支援：{kind}")

    for key in (
        "options",
        "exclusive_options",
        "quick_options",
        "units",
    ):
        _validate_string_list(
            item[key],
            category=category,
            field=field,
            key=key,
        )

    if kind == "choice" and not item["options"]:
        raise ValueError(f"{category}.json 的選擇題 {field} 必須提供 options")
    if kind == "duration" and (not item["quick_options"] or not item["units"]):
        raise ValueError(f"{category}.json 的時間題 {field} 必須提供 quick_options 與 units")
    if not set(item["exclusive_options"]).issubset(item["options"]):
        raise ValueError(f"{category}.json 的 {field}.exclusive_options 必須存在於 options")

    semantic_options = item["semantic_options"]
    if not isinstance(semantic_options, dict):
        raise ValueError(f"{category}.json 的 {field}.semantic_options 必須是物件")
    unknown_semantic_options = set(semantic_options) - set(item["options"])
    if unknown_semantic_options:
        raise ValueError(f"{category}.json 的 {field}.semantic_options 只能引用既有選項")
    for option, facts in semantic_options.items():
        if not isinstance(facts, dict) or not facts:
            raise ValueError(f"{category}.json 的 {field}.semantic_options.{option} 必須是非空物件")
        unknown_fact_keys = set(facts) - {
            "onset",
            "severity",
            "new_or_changed",
            "findings",
        }
        if unknown_fact_keys:
            raise ValueError(
                f"{category}.json 的 {field}.semantic_options.{option} "
                f"含不支援欄位：{sorted(unknown_fact_keys)}"
            )
        scalar_domains = {
            "onset": {"sudden", "gradual"},
            "severity": {"mild", "moderate", "severe"},
            "new_or_changed": {"true", "false"},
        }
        for fact_key, allowed in scalar_domains.items():
            if fact_key in facts and facts[fact_key] not in allowed:
                raise ValueError(
                    f"{category}.json 的 {field}.semantic_options.{option}.{fact_key} 值不正確"
                )
        if "findings" in facts:
            _validate_string_list(
                facts["findings"],
                category=category,
                field=field,
                key=f"semantic_options.{option}.findings",
            )

    condition = item.get("condition")
    if condition is not None:
        if not isinstance(condition, dict) or not isinstance(condition.get("field"), str):
            raise ValueError(f"{category}.json 的 {field}.condition 格式錯誤")
        _validate_string_list(
            condition.get("contains_any"),
            category=category,
            field=field,
            key="condition.contains_any",
        )

    return item


@lru_cache(maxsize=len(QUESTIONNAIRE_CATEGORIES))
def load_questionnaire_category(
    category: str,
) -> tuple[dict[str, Any], ...]:
    """依需求讀取一個分類檔，驗證後快取。"""
    if category not in QUESTIONNAIRE_CATEGORIES:
        raise ValueError(f"不支援的問卷分類：{category}")

    path = QUESTIONNAIRE_DATA_DIR / f"{category}.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"找不到問卷檔案：{path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"問卷 JSON 格式錯誤：{path}:{exc.lineno}:{exc.colno}") from exc

    if not isinstance(document, dict) or document.get("id") != category:
        raise ValueError(f"{path.name} 的 id 必須是 {category}")
    section = document.get("section")
    if section not in SECTION_LABELS:
        raise ValueError(f"{path.name} 的 section 不正確：{section}")
    raw_questions = document.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise ValueError(f"{path.name} 必須包含非空 questions")

    questions = tuple(
        _validate_question(
            raw,
            category=category,
            section=section,
            position=position,
        )
        for position, raw in enumerate(raw_questions)
    )
    fields = [item["field"] for item in questions]
    if len(fields) != len(set(fields)):
        raise ValueError(f"{path.name} 不可有重複 field")
    return questions


class _LazyDiseaseQuestionnaires(Mapping[str, tuple[dict[str, Any], ...]]):
    """維持既有 mapping 介面，但只在取用路由時載入 JSON。"""

    def __getitem__(self, route: str) -> tuple[dict[str, Any], ...]:
        if route not in DISEASE_ROUTES:
            raise KeyError(route)
        return load_questionnaire_category(route)

    def __iter__(self) -> Iterator[str]:
        return iter(DISEASE_ROUTES)

    def __len__(self) -> int:
        return len(DISEASE_ROUTES)


# 入口與共用問卷啟動時載入；疾病問卷依 LLM 路由 lazy-load。
CHIEF_QUESTIONNAIRE = load_questionnaire_category("chief")
BASIC_QUESTIONNAIRE = load_questionnaire_category("basic")
HISTORY_QUESTIONNAIRE = load_questionnaire_category("history")
DISEASE_QUESTIONNAIRES = _LazyDiseaseQuestionnaires()


def build_questionnaire(route: str) -> list[dict[str, Any]]:
    """組合主訴、基本資料、病史與指定疾病問卷。"""
    if route not in DISEASE_ROUTES:
        raise ValueError(f"不支援的疾病問卷路由：{route}")
    return deepcopy(
        [
            *CHIEF_QUESTIONNAIRE,
            *BASIC_QUESTIONNAIRE,
            *HISTORY_QUESTIONNAIRE,
            *DISEASE_QUESTIONNAIRES[route],
        ]
    )


def condition_matches(item: dict[str, Any], data: dict[str, Any]) -> bool:
    condition = item.get("condition")
    if not condition:
        return True
    value = str(data.get(condition["field"], ""))
    return any(token in value for token in condition.get("contains_any", []))


def next_question_index(
    questionnaire: list[dict[str, Any]],
    current_index: int,
    data: dict[str, Any],
    skip_fields: set[str] | None = None,
) -> int | None:
    skip_fields = skip_fields or set()
    for index in range(current_index + 1, len(questionnaire)):
        if questionnaire[index]["field"] not in skip_fields and condition_matches(
            questionnaire[index], data
        ):
            return index
    return None


def question_input(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in item.items() if key not in {"condition", "semantic_options"}
    }


def questionnaire_meta(
    item: dict[str, Any],
    route: str | None,
) -> dict[str, Any]:
    section = item["section"]
    return {
        "section": section,
        "label": SECTION_LABELS[section],
        "route": route,
        "route_label": ROUTE_LABELS.get(route or "", ""),
    }


def progress_meta(
    questionnaire: list[dict[str, Any]],
    current_index: int,
    data: dict[str, Any],
) -> dict[str, int]:
    active = [item for item in questionnaire if condition_matches(item, data)]
    current = sum(
        1
        for index, item in enumerate(questionnaire)
        if index <= current_index and condition_matches(item, data)
    )
    total = max(len(active), 1)
    return {
        "current": current,
        "total": total,
        "percent": min(100, round((current / total) * 100)),
    }


_ONSET_PATTERN = re.compile(
    r"(?P<number>\d+(?:\.\d+)?)\s*(?:個)?"
    r"(?P<unit>分鐘|分|小時|鐘頭|天|日|週|周|星期|個月|月|年)"
)
_SIMPLE_CN_NUMBER = re.compile(r"[零一二兩三四五六七八九十百]+")


def _normalize_onset_numbers(text: str) -> str:
    digits = {
        "零": 0,
        "一": 1,
        "二": 2,
        "兩": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }

    def convert(match: re.Match) -> str:
        value = match.group(0)
        if value in digits:
            return str(digits[value])
        total = 0
        current = 0
        for char in value:
            if char in digits:
                current = digits[char]
            elif char == "十":
                total += (current or 1) * 10
                current = 0
            elif char == "百":
                total += (current or 1) * 100
                current = 0
        return str(total + current)

    return _SIMPLE_CN_NUMBER.sub(convert, text)


def parse_onset_answer(text: str) -> tuple[str, str] | None:
    """解析分鐘、小時、天、週、月與年，不猜測缺少的單位。"""
    normalized = _normalize_onset_numbers(text.strip())
    relative = {
        "剛剛": ("剛剛", ""),
        "今天": ("今天", ""),
        "昨天": ("1", "天前"),
        "前天": ("2", "天前"),
    }
    for token, value in relative.items():
        if token in normalized:
            return value

    match = _ONSET_PATTERN.search(normalized)
    if not match:
        return None

    unit_map = {
        "分鐘": "分鐘前",
        "分": "分鐘前",
        "小時": "小時前",
        "鐘頭": "小時前",
        "天": "天前",
        "日": "天前",
        "週": "週前",
        "周": "週前",
        "星期": "週前",
        "個月": "個月前",
        "月": "個月前",
        "年": "年前",
    }
    return match.group("number"), unit_map[match.group("unit")]


def parse_birth_date(
    text: str,
    today: date | None = None,
) -> tuple[str, int] | None:
    try:
        value = date.fromisoformat(text.strip())
    except ValueError:
        return None

    today = today or date.today()
    if value > today:
        return None
    age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
    if age < 0 or age > 130:
        return None
    return value.isoformat(), age
