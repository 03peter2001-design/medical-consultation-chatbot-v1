"""將既有文字問卷轉成前端可渲染的結構化選項。"""

from __future__ import annotations

import re


_OPTION_LINE = re.compile(r"^選項[：:]\s*(.+)$", re.MULTILINE)
_PAREN_CHOICE = re.compile(r"[（(]([^（）()]*\s/\s[^（）()]*)[）)]")
_MULTI_HINT = re.compile(r"[（(]可複選[^）)]*[）)]")

_MANUAL_OPTIONS = {
    ("chest", 7): ["左邊", "右邊", "正中間", "兩側都有"],
}
_MANUAL_PROMPTS = {
    ("chest", 7): "胸痛的位置在哪裡？",
}

_EXCLUSIVE_OPTIONS = {"以上皆無", "未曾手術"}


def _normalize_option(option: str) -> str | None:
    value = option.strip().strip("。；;")
    if not value:
        return None
    if value.startswith("其他"):
        return None
    if value.startswith("有，請") or value.startswith("有,請"):
        return "有"
    return value


def _split_options(source: str, separator: str) -> list[str]:
    options = []
    for raw in source.split(separator):
        value = _normalize_option(raw)
        if value and value not in options:
            options.append(value)
    return options


def build_question_input(
    question: str,
    *,
    step: int,
    ctype: str,
) -> dict | None:
    """回傳 choice input spec；純文字題目回傳 None。"""
    manual = _MANUAL_OPTIONS.get((ctype, step))
    option_source = ""
    options: list[str] = []

    if step == 0:
        options = ["男性", "女性"]
    elif manual:
        options = list(manual)
    else:
        line_match = _OPTION_LINE.search(question)
        if line_match:
            option_source = line_match.group(0)
            options = _split_options(line_match.group(1), "、")
        else:
            paren_match = _PAREN_CHOICE.search(question)
            if paren_match:
                option_source = paren_match.group(0)
                options = _split_options(paren_match.group(1), "/")

    if not options:
        return None

    multiple = "可複選" in question
    prompt = question
    manual_prompt = _MANUAL_PROMPTS.get((ctype, step))
    if manual_prompt:
        prompt = manual_prompt
    if option_source:
        prompt = prompt.replace(option_source, "")
    prompt = _MULTI_HINT.sub("", prompt)
    prompt = prompt.replace("可以複選：", "")
    prompt = re.sub(r"\n{3,}", "\n\n", prompt).strip()

    return {
        "kind": "choice",
        "multiple": multiple,
        "options": options,
        "exclusive_options": [
            option for option in options if option in _EXCLUSIVE_OPTIONS
        ],
        "allow_other": True,
        "other_label": "其他／補充說明",
        "prompt": prompt,
        "question": question,
    }
