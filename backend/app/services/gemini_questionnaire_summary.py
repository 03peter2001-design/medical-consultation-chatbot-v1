"""Gemini conversion of a completed questionnaire into a six-part clinical note."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from app.prompts.questionnaire_summary import EMR_TASKS, PROMPT_VERSION, SUMMARY_TASKS

EMR_FIELD_BY_TASK = {
    "chief_complaint": "cc",
    "present_illness": "pi",
    "past_history": "ph",
    "drug_history": "meds",
    "drug_allergy_history": "allergy",
    "personal_history": "personal",
    "family_history": "family",
}


@dataclass(frozen=True)
class GeminiQuestionnaireSummary:
    emr: dict[str, str]
    differential_diagnoses: list[str]
    must_not_miss: list[str]
    physical_examination: list[str]
    laboratory: list[str]
    imaging: list[str]


def _clean_text(value: str, *, limit: int) -> str:
    """Bound model text and preserve the report's direct clinical-plan language."""

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


def _parse_items(
    payload: dict[str, Any],
    field: str,
    *,
    limit: int,
) -> list[str]:
    raw_items = payload.get(field)
    if not isinstance(raw_items, list):
        raise ValueError(f"Gemini {field} must be a list")
    items: list[str] = []
    for raw in raw_items[:limit]:
        if not isinstance(raw, str):
            raise ValueError(f"Gemini {field} items must be text")
        item = _clean_text(raw, limit=1200)
        if item:
            items.append(item)
    return items


def _parse_json_object(raw: str) -> dict[str, Any]:
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
    if not isinstance(payload, dict):
        raise ValueError("Gemini questionnaire summary has an invalid shape")
    return payload


def _medical_english_sex(value: str | None) -> str:
    normalized = str(value or "").strip()
    return {
        "男": "male",
        "男性": "male",
        "male": "male",
        "女": "female",
        "女性": "female",
        "female": "female",
        "其他": "other",
        "other": "other",
    }.get(normalized.lower(), normalized or "Not provided")


def _chief_complaint_sentence(
    complaint: str,
    *,
    patient_age: str | None,
    patient_sex: str | None,
) -> str:
    age = str(patient_age or "").strip().removesuffix("歲")
    sex = _medical_english_sex(patient_sex)
    symptom = complaint.strip().rstrip(". ") or "Not provided"
    if age and sex != "Not provided":
        subject = f"A {age}-year-old {sex} patient"
    elif age:
        subject = f"A {age}-year-old patient (sex: Not provided)"
    elif sex != "Not provided":
        subject = f"A {sex} patient (age: Not provided)"
    else:
        subject = "A patient (age: Not provided; sex: Not provided)"
    return f"{subject} presents with {symptom}."


def parse_summary_section(task: str, raw: str) -> str | list[str]:
    """Validate one task response before it can influence a later request."""

    if task not in SUMMARY_TASKS:
        raise ValueError(f"unknown Gemini questionnaire summary task: {task}")
    payload = _parse_json_object(raw)
    if set(payload) != {task}:
        raise ValueError(f"Gemini {task} response has an invalid shape")
    value = payload[task]
    if task in EMR_TASKS:
        if not isinstance(value, str):
            raise ValueError(f"Gemini {task} must be text")
        return _clean_text(value, limit=4000) or "Not provided"

    limits = {
        "differential_diagnoses": 3,
        "must_not_miss": 5,
        "physical_examination": 4,
        "laboratory": 8,
        "imaging": 6,
    }
    return _parse_items({task: value}, task, limit=limits[task])


def parse_summary_sections(
    raw_sections: Mapping[str, str],
    *,
    patient_age: str | None = None,
    patient_sex: str | None = None,
) -> GeminiQuestionnaireSummary:
    """Validate all independently generated sections before constructing a report."""

    if set(raw_sections) != set(SUMMARY_TASKS):
        raise ValueError("Gemini questionnaire summary has missing or extra tasks")
    sections = {task: parse_summary_section(task, raw_sections[task]) for task in SUMMARY_TASKS}
    emr = {field: cast(str, sections[task]) for task, field in EMR_FIELD_BY_TASK.items()}
    emr["cc"] = _chief_complaint_sentence(
        emr["cc"],
        patient_age=patient_age,
        patient_sex=patient_sex,
    )

    return GeminiQuestionnaireSummary(
        emr=emr,
        differential_diagnoses=cast(list[str], sections["differential_diagnoses"]),
        must_not_miss=cast(list[str], sections["must_not_miss"]),
        physical_examination=cast(list[str], sections["physical_examination"]),
        laboratory=cast(list[str], sections["laboratory"]),
        imaging=cast(list[str], sections["imaging"]),
    )


def parse_summary(raw: str) -> GeminiQuestionnaireSummary:
    """Parse a combined response shape for internal compatibility."""

    payload = _parse_json_object(raw)
    if set(payload) != set(SUMMARY_TASKS):
        raise ValueError("Gemini questionnaire summary has an invalid shape")
    return parse_summary_sections(
        {task: json.dumps({task: payload[task]}, ensure_ascii=False) for task in SUMMARY_TASKS}
    )


def _numbered_items(
    items: list[str],
    *,
    total: int | None = None,
) -> str:
    rendered = [f"{index}. {item}" for index, item in enumerate(items, start=1)]
    if total is not None:
        rendered.extend(
            f"{index}. Insufficient evidence; defer to clinical judgment."
            for index in range(len(rendered) + 1, total + 1)
        )
    return "\n".join(rendered) or "Insufficient evidence; defer to clinical judgment."


def render_emr(summary: GeminiQuestionnaireSummary, *, model: str) -> str:
    emr = summary.emr
    return f"""【病歷摘要 EMR】
Chief Complaint:
{emr["cc"]}

Present Illness:
{emr["pi"]}

Past History:
{emr["ph"]}

Drug History:
{emr["meds"]}

Allergy History:
{emr["allergy"]}

Personal History:
{emr["personal"]}

Family History:
{emr["family"]}

【初步鑑別診斷（前3項最可能）】
{_numbered_items(summary.differential_diagnoses, total=3)}

【防漏診鑑別 — 5個絕對不能漏掉的隱形殺手】
{_numbered_items(summary.must_not_miss, total=5)}

【理學檢查】
{_numbered_items(summary.physical_examination)}

【檢驗（抽血／驗尿）】
{_numbered_items(summary.laboratory)}

【影像學決策】
{_numbered_items(summary.imaging)}

模型：{model}｜Prompt：{PROMPT_VERSION}

本分析由 Gemini 依固定問卷與 RAG 文獻生成，尚未經醫師確認，不代表正式診斷或已簽署醫囑。"""
