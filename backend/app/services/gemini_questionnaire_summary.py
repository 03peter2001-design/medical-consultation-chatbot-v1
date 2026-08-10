"""Gemini conversion of a completed questionnaire into a six-part clinical note."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

PROMPT_VERSION = "fixed-questionnaire-six-part-rag-v3"
EMR_FIELDS = ("cc", "pi", "ph", "meds", "allergy")
LIST_FIELDS = (
    "differential_diagnoses",
    "must_not_miss",
    "physical_examination",
    "laboratory",
    "imaging",
)


@dataclass(frozen=True)
class GeminiQuestionnaireSummary:
    emr: dict[str, str]
    differential_diagnoses: list[dict[str, str]]
    must_not_miss: list[dict[str, str]]
    physical_examination: list[dict[str, str]]
    laboratory: list[dict[str, str]]
    imaging: list[dict[str, str]]


def _without_advice_word(value: str, *, limit: int) -> str:
    """Keep the report in direct clinical-plan language requested by the product owner."""

    return value.strip().replace("建議立即", "應立即").replace("建議", "").strip()[:limit]


def questionnaire_answers(
    questionnaire: list[dict[str, Any]],
    data: dict[str, Any],
) -> list[dict[str, str]]:
    """Return every answered fixed question in source order."""

    answers: list[dict[str, str]] = []
    for question in questionnaire:
        field = str(question.get("field") or "")
        if not field or field not in data:
            continue
        raw_answer = data.get(field)
        if raw_answer in (None, "", [], {}):
            continue
        answer = (
            "、".join(str(item) for item in raw_answer)
            if isinstance(raw_answer, list)
            else str(raw_answer)
        )
        answers.append(
            {
                "field": field,
                "question": str(question.get("prompt") or field),
                "answer": answer,
            }
        )
    return answers


def build_summary_messages(
    answers: list[dict[str, str]],
    *,
    prefilled_data: dict[str, Any],
    knowledge_contexts: dict[str, str],
) -> list[dict[str, str]]:
    """Build the single Gemini request made after all fixed questions finish."""

    prefill = {
        key: value
        for key, value in prefilled_data.items()
        if not key.startswith("_") and value not in (None, "", [], {})
    }
    system_prompt = """
請以資深急診醫師向第一線醫護交班的格式，將固定問卷整理成繁體中文結構化病歷與
臨床決策分析。語氣專業精簡；不可把初步鑑別寫成已確診，也不可加入問卷、院方預填
資料或醫學知識庫中不存在的病人事實。

鑑別與防漏診理由必須以醫學知識庫 A 為依據；檢驗項目使用知識庫 B；影像項目使用
知識庫 C。知識庫不足時直接填「知識庫未涵蓋此項」，不可編造依據。這個流程沒有
疾病投票或後端 Safety 規則，所有疾病與臨床決策都是 Gemini 依輸入產生的未確認內容。

只回傳一個 JSON object，不要輸出 Markdown、段落標題或其他文字：
{
  "emr": {
    "cc": "主訴",
    "pi": "現病史，可使用標準醫學英文敘述",
    "ph": "過去病史",
    "meds": "用藥",
    "allergy": "過敏史"
  },
  "differential_diagnoses": [
    {"name": "前3項最可能的疾病名稱（可含英文）", "rationale": "簡短理由"}
  ],
  "must_not_miss": [
    {"name": "最多5項不能漏掉的嚴重鑑別", "rationale": "知識庫A依據與不能漏掉的理由"}
  ],
  "physical_examination": [
    {"item": "2～4項床邊理學檢查", "rationale": "要觀察的重點"}
  ],
  "laboratory": [
    {"item": "有鑑別力的抽血／驗尿項目", "rationale": "知識庫B依據與目的"}
  ],
  "imaging": [
    {"item": "影像項目", "rationale": "知識庫C依據；CT/MRI需說明不能由基礎影像取代的原因"}
  ]
}

限制：
- 嚴格維持上述欄位，不增加患者端衛教或額外結論
- 不輸出名為「建議」的段落，也不要使用「理學檢查建議」或「檢驗建議」作為標題
- differential_diagnoses 最多3項，must_not_miss 最多5項
- 不做正式診斷；缺乏輸入依據時明確寫資料不足
""".strip()
    payload = {
        "prefilled_data": prefill,
        "questionnaire_answers": answers,
        "medical_knowledge": {
            "A_differential_and_danger_signs": knowledge_contexts.get(
                "diagnosis", "（知識庫中查無相關內容）"
            ),
            "B_laboratory": knowledge_contexts.get("laboratory", "（知識庫中查無相關內容）"),
            "C_imaging": knowledge_contexts.get("imaging", "（知識庫中查無相關內容）"),
        },
    }
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def _parse_items(
    payload: dict[str, Any],
    field: str,
    *,
    name_key: str,
    limit: int,
) -> list[dict[str, str]]:
    raw_items = payload.get(field)
    if not isinstance(raw_items, list):
        raise ValueError(f"Gemini {field} must be a list")
    items: list[dict[str, str]] = []
    for raw in raw_items[:limit]:
        if not isinstance(raw, dict) or set(raw) - {name_key, "rationale"}:
            raise ValueError(f"Gemini {field} item has an invalid shape")
        name = raw.get(name_key)
        rationale = raw.get("rationale")
        if not isinstance(name, str) or not isinstance(rationale, str):
            raise ValueError(f"Gemini {field} item values must be text")
        name = _without_advice_word(name, limit=300)
        rationale = _without_advice_word(rationale, limit=1000)
        if name and rationale:
            items.append(
                {
                    name_key: name,
                    "rationale": rationale,
                }
            )
    return items


def parse_summary(raw: str) -> GeminiQuestionnaireSummary:
    candidate = str(raw or "").strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise ValueError("Gemini questionnaire summary is not valid JSON") from error
    if not isinstance(payload, dict) or set(payload) != {"emr", *LIST_FIELDS}:
        raise ValueError("Gemini questionnaire summary has an invalid shape")

    raw_emr = payload.get("emr")
    if not isinstance(raw_emr, dict) or set(raw_emr) != set(EMR_FIELDS):
        raise ValueError("Gemini emr has an invalid shape")
    emr: dict[str, str] = {}
    for field in EMR_FIELDS:
        value = raw_emr.get(field)
        if not isinstance(value, str):
            raise ValueError("Gemini emr fields must be text")
        emr[field] = _without_advice_word(value, limit=4000) or "未提供"

    return GeminiQuestionnaireSummary(
        emr=emr,
        differential_diagnoses=_parse_items(
            payload,
            "differential_diagnoses",
            name_key="name",
            limit=3,
        ),
        must_not_miss=_parse_items(payload, "must_not_miss", name_key="name", limit=5),
        physical_examination=_parse_items(
            payload,
            "physical_examination",
            name_key="item",
            limit=4,
        ),
        laboratory=_parse_items(payload, "laboratory", name_key="item", limit=8),
        imaging=_parse_items(payload, "imaging", name_key="item", limit=6),
    )


def _numbered_items(
    items: list[dict[str, str]],
    *,
    name_key: str,
    total: int | None = None,
) -> str:
    rendered = [
        f"{index}. {item[name_key]}\n   理由：{item['rationale']}"
        for index, item in enumerate(items, start=1)
    ]
    if total is not None:
        rendered.extend(
            f"{index}. 資料不足\n   理由：知識庫未涵蓋此項。"
            for index in range(len(rendered) + 1, total + 1)
        )
    return "\n".join(rendered) or "資料不足：知識庫未涵蓋此項。"


def render_emr(summary: GeminiQuestionnaireSummary, *, model: str) -> str:
    emr = summary.emr
    return f"""【病歷摘要 EMR】
CC（主訴）：
{emr["cc"]}

PI（現病史）：
{emr["pi"]}

PH（過去病史）：
{emr["ph"]}

Meds（用藥）：
{emr["meds"]}

Allergy（過敏史）：
{emr["allergy"]}

【初步鑑別診斷（前3項最可能）】
{_numbered_items(summary.differential_diagnoses, name_key="name", total=3)}

【防漏診鑑別 — 5個絕對不能漏掉的隱形殺手】
{_numbered_items(summary.must_not_miss, name_key="name", total=5)}

【理學檢查】
{_numbered_items(summary.physical_examination, name_key="item")}

【檢驗（抽血／驗尿）】
{_numbered_items(summary.laboratory, name_key="item")}

【影像學決策】
{_numbered_items(summary.imaging, name_key="item")}

模型：{model}｜Prompt：{PROMPT_VERSION}

本分析由 Gemini 依固定問卷與 RAG 文獻生成，尚未經醫師確認，不代表正式診斷或已簽署醫囑。"""
