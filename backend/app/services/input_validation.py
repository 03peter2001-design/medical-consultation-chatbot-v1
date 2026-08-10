"""Strict validation for answers emitted by the structured questionnaire UI."""

from __future__ import annotations

import re

from domain.body_pain_regions import serialize_pain_locations
from domain.patient_messages import patient_message
from domain.questionnaires import parse_birth_date

OTHER_PREFIX = "其他："
PREFILL_GENDERS = {"男性", "女性", "其他", "不便透露"}
_PUNCTUATION_ONLY = re.compile(r"^[\s。！？，、….!?.,;；：:]+$")


def prefill_gender_is_valid(value: str) -> bool:
    return value in PREFILL_GENDERS or (
        value.startswith(OTHER_PREFIX) and bool(value[len(OTHER_PREFIX) :].strip())
    )


def _is_invalid_answer(text: str) -> bool:
    value = text.strip()
    return not value or bool(_PUNCTUATION_ONLY.fullmatch(value))


def _choice_answer_is_valid(question: dict, answer: str) -> bool:
    option_text = answer
    other_text = ""
    other_marker = f"、{OTHER_PREFIX}"
    if answer.startswith(OTHER_PREFIX):
        option_text = ""
        other_text = answer[len(OTHER_PREFIX) :].strip()
    elif other_marker in answer:
        option_text, other_text = answer.split(other_marker, 1)
        other_text = other_text.strip()

    if other_text and not question.get("allow_other"):
        return False
    if OTHER_PREFIX in option_text or (
        question.get("allow_other") and not option_text and not other_text
    ):
        return False

    selected = option_text.split("、") if option_text else []
    options = set(question.get("options", []))
    if (
        not selected
        and not other_text
        or len(selected) != len(set(selected))
        or any(value not in options for value in selected)
    ):
        return False
    if not question.get("multiple") and len(selected) + bool(other_text) != 1:
        return False

    exclusive = set(question.get("exclusive_options", []))
    if exclusive.intersection(selected) and (len(selected) > 1 or bool(other_text)):
        return False
    return True


def _duration_parts(
    question: dict,
    answer: str,
) -> tuple[str, str] | None:
    """Read an exact numeric duration without translating free text."""
    units = sorted(
        question.get("units", []),
        key=len,
        reverse=True,
    )
    if not units:
        return None
    pattern = re.compile(
        rf"^(?P<number>\d+(?:\.\d+)?)(?P<unit>"
        rf"{'|'.join(re.escape(unit) for unit in units)})$"
    )
    match = pattern.fullmatch(answer)
    if not match or float(match.group("number")) <= 0:
        return None
    return match.group("number"), match.group("unit")


def validate_question_answer(
    question: dict,
    answer: str,
    *,
    pain_location_ids: list[str] | None = None,
) -> str | None:
    """Return an error message when a structured UI answer is invalid."""
    if _is_invalid_answer(answer):
        return patient_message("validation.empty")

    field = question.get("base_field", question.get("field", ""))
    kind = question.get("kind", "text")
    if field == "location" and pain_location_ids:
        return None
    if kind == "choice" and not _choice_answer_is_valid(question, answer):
        return patient_message("validation.choice")
    if kind == "date" and parse_birth_date(answer) is None:
        return patient_message("validation.date")
    if kind == "duration":
        is_quick_option = answer in question.get("quick_options", [])
        has_duration_parts = _duration_parts(question, answer) is not None
        is_explicit_other = question.get("allow_other") and not re.match(r"^\d", answer)
        if not (is_quick_option or has_duration_parts or is_explicit_other):
            return patient_message("validation.duration")
    return None


def store_question_answer(
    data: dict,
    question: dict,
    answer: str,
    *,
    pain_location_ids: list[str] | None = None,
) -> tuple[str, str]:
    """Store validated input as submitted, deriving only structural fields."""
    field = question["field"]
    base_field = question.get("base_field", field)
    field_prefix = field[: -len(base_field)] if field != base_field else ""
    stored_answer = answer

    if base_field == "location" and pain_location_ids:
        pain_locations = serialize_pain_locations(pain_location_ids)
        data[f"{field_prefix}pain_locations"] = pain_locations
        stored_answer = "、".join(location["label"] for location in pain_locations)

    if question.get("kind") == "date":
        parsed_birth_date = parse_birth_date(stored_answer)
        if parsed_birth_date is None:
            raise ValueError("store_question_answer 只能接收已驗證的日期")
        birth_date, age = parsed_birth_date
        data[field] = birth_date
        if field == "birth_date":
            data["age"] = str(age)
        return stored_answer, birth_date

    data[field] = stored_answer
    if question.get("kind") == "duration":
        parts = _duration_parts(question, stored_answer)
        onset_num_field = f"{field_prefix}onset_num"
        onset_unit_field = f"{field_prefix}onset_unit"
        if parts:
            data[onset_num_field], data[onset_unit_field] = parts
        else:
            data.pop(onset_num_field, None)
            data.pop(onset_unit_field, None)
    return stored_answer, stored_answer
