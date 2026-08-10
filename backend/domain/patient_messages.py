"""Validated, data-driven copy used by the patient interview flow."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from string import Formatter
from typing import Any

PATIENT_MESSAGES_PATH = (
    Path(__file__).resolve().parents[1] / "questionnaire_data" / "ui" / "patient_messages.json"
)

EXPECTED_MESSAGE_FIELDS = {
    "label.symptom": frozenset(),
    "navigation.no_previous_question": frozenset(),
    "navigation.previous_question": frozenset({"prompt"}),
    "interview.amie_welcome": frozenset({"prompt"}),
    "interview.legacy_welcome": frozenset({"prompt"}),
    "interview.already_completed": frozenset(),
    "interview.validation_retry": frozenset({"validation_error", "prompt"}),
    "interview.acknowledgement_question": frozenset({"acknowledgement", "prompt"}),
    "section.basic": frozenset({"prompt"}),
    "section.history_prefilled_basic": frozenset({"prompt"}),
    "section.history": frozenset({"prompt"}),
    "section.disease_prefilled_all": frozenset({"route_label", "prompt"}),
    "section.disease_prefilled_basic": frozenset({"route_label", "prompt"}),
    "section.disease": frozenset({"route_label", "prompt"}),
    "validation.empty": frozenset(),
    "validation.choice": frozenset(),
    "validation.date": frozenset(),
    "validation.duration": frozenset(),
    "completion.routine": frozenset({"queue_number"}),
    "completion.urgent": frozenset({"urgent_care_message", "queue_number"}),
    "safety.urgent_care": frozenset(),
    "handoff.reply": frozenset({"labels", "queue_number"}),
    "handoff.label_default": frozenset(),
    "handoff.safety_unavailable": frozenset(),
    "handoff.unsupported_route": frozenset(),
    "handoff.reason.safety_unavailable": frozenset(),
    "handoff.reason.unsupported_route": frozenset(),
    "handoff.reason.processing_timeout": frozenset(),
    "handoff.reason.default": frozenset(),
    "handoff.reason.no_next_question": frozenset(),
    "handoff.reason.unapproved_next_question": frozenset(),
    "handoff.reason.route_disposition": frozenset({"route_label"}),
    "report.summary_pending": frozenset(),
    "report.urgent_trigger_default": frozenset(),
    "report.urgent_condition_line": frozenset({"condition_summary"}),
    "report.urgent": frozenset(
        {
            "urgent_care_message",
            "trigger_labels",
            "condition_line",
            "summary_pending",
        }
    ),
    "report.handoff_trigger_default": frozenset(),
    "report.handoff": frozenset({"reason", "trigger_labels"}),
}


def _template_fields(template: str, *, key: str) -> frozenset[str]:
    fields: set[str] = set()
    for _, field_name, format_spec, conversion in Formatter().parse(template):
        if field_name is None:
            continue
        if not field_name.isidentifier() or format_spec or conversion:
            raise ValueError(f"patient_messages.json 的 {key} 含不支援的格式欄位")
        fields.add(field_name)
    return frozenset(fields)


def load_patient_messages(path: Path = PATIENT_MESSAGES_PATH) -> dict[str, str]:
    try:
        document: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"找不到病患問診文案：{path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"病患問診文案 JSON 格式錯誤：{path}:{exc.lineno}:{exc.colno}") from exc

    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "locale", "messages"}
        or document.get("schema_version") != 1
        or document.get("locale") != "zh-TW"
        or not isinstance(document.get("messages"), dict)
    ):
        raise ValueError("patient_messages.json 根節點格式不正確")

    messages = document["messages"]
    if set(messages) != set(EXPECTED_MESSAGE_FIELDS):
        missing = sorted(set(EXPECTED_MESSAGE_FIELDS) - set(messages))
        extra = sorted(set(messages) - set(EXPECTED_MESSAGE_FIELDS))
        raise ValueError(f"patient_messages.json 文案不同步；missing={missing}, extra={extra}")

    validated: dict[str, str] = {}
    for key, expected_fields in EXPECTED_MESSAGE_FIELDS.items():
        template = messages[key]
        if not isinstance(template, str) or not template.strip():
            raise ValueError(f"patient_messages.json 的 {key} 必須是非空字串")
        actual_fields = _template_fields(template, key=key)
        if actual_fields != expected_fields:
            raise ValueError(
                f"patient_messages.json 的 {key} placeholders 不正確；"
                f"expected={sorted(expected_fields)}, actual={sorted(actual_fields)}"
            )
        validated[key] = template
    return validated


@lru_cache(maxsize=1)
def patient_messages() -> dict[str, str]:
    return load_patient_messages()


def patient_message(key: str, **values: object) -> str:
    expected_fields = EXPECTED_MESSAGE_FIELDS.get(key)
    if expected_fields is None:
        raise KeyError(f"未知病患問診文案：{key}")
    if set(values) != set(expected_fields):
        raise ValueError(
            f"病患問診文案 {key} 參數不正確；"
            f"expected={sorted(expected_fields)}, actual={sorted(values)}"
        )
    return patient_messages()[key].format(**values)
