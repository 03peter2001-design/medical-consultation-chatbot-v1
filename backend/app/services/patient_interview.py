"""Session and questionnaire preparation helpers for patient interviews."""

import re
import time

from amie.clinical_facts import (
    filter_question_by_questionnaire_answers,
    questionnaire_prefills_from_assessment,
)
from amie.models import ChiefComplaintAssessment
from amie.rule_config import load_safety_rules
from app.models import ChatRequest
from app.services.input_validation import prefill_gender_is_valid
from domain.patient_messages import patient_message
from domain.questionnaires import (
    CHIEF_QUESTIONNAIRE,
    DISEASE_ROUTES,
    ROUTE_KEYWORDS,
    ROUTE_LABELS,
    parse_birth_date,
)
from domain.terminology_reference import filter_supported_codings

SUPPORTED_PATIENT_ROUTES = frozenset(DISEASE_ROUTES)
URGENT_CONDITION_CANDIDATES = load_safety_rules()["urgent_condition_candidates"]


def _keyword_matches(text: str, keyword: str) -> bool:
    normalized = text.casefold()
    token = keyword.casefold()
    if token.isascii() and any(character.isalpha() for character in token):
        starts = (
            match.start()
            for match in re.finditer(
                rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])",
                normalized,
            )
        )
    else:
        starts = (match.start() for match in re.finditer(re.escape(token), normalized))
    for start in starts:
        prefix = normalized[max(0, start - 8) : start]
        if not re.search(r"(?:沒有|否認|不是|並未|未曾)\s*$", prefix):
            return True
    return False


def route_keyword_hits(text: str) -> dict[str, bool]:
    return {
        route: any(_keyword_matches(text, keyword) for keyword in keywords)
        for route, keywords in ROUTE_KEYWORDS.items()
    }


def local_complaint_route(text: str) -> str | None:
    """Return one route only when matched concepts are not independently ambiguous."""
    matches = {
        route: [keyword for keyword in keywords if _keyword_matches(text, keyword)]
        for route, keywords in ROUTE_KEYWORDS.items()
    }
    matches = {route: values for route, values in matches.items() if values}
    if len(matches) <= 1:
        return next(iter(matches), None)

    # A generic token such as「無力」must not make「半身無力」ambiguous with
    # the more specific stroke route. Independent concepts (e.g. 頭痛＋腹痛)
    # remain ambiguous so the semantic extractor can retain both routes.
    remaining = []
    for route, values in matches.items():
        dominated = all(
            any(
                value.casefold() in other.casefold() and len(other) > len(value)
                for other_route, other_values in matches.items()
                if other_route != route
                for other in other_values
            )
            for value in values
        )
        if not dominated:
            remaining.append(route)
    return remaining[0] if len(remaining) == 1 else None


def urgent_possible_conditions(session: dict) -> list[str]:
    """Return stable, deduplicated candidates attached to triggered rules."""
    flags = session.get("amie_state", {}).get("red_flags", [])
    conditions = []
    for flag in flags:
        configured = flag.get("possible_conditions") or (
            URGENT_CONDITION_CANDIDATES.get(flag.get("label", ""), [])
        )
        conditions.extend(
            condition.strip()
            for condition in configured
            if isinstance(condition, str) and condition.strip()
        )
    return list(dict.fromkeys(conditions))


def prefilled_patient_data(req: ChatRequest) -> tuple[dict, set[str]]:
    prefill = req.patient_prefill.model_dump(exclude_none=True) if req.patient_prefill else {}
    prefill.pop("source", None)
    clinical_codings = filter_supported_codings(prefill.pop("clinical_codings", []))
    data: dict = {}
    if clinical_codings:
        data["_clinical_codings"] = clinical_codings
    prefilled_fields: set[str] = set()
    for field, value in prefill.items():
        if not value:
            continue
        if field == "birth_date":
            parsed_birth_date = parse_birth_date(value)
            if parsed_birth_date is None:
                continue
            data["birth_date"], age = parsed_birth_date
            data["age"] = str(age)
        elif field == "gender":
            if not prefill_gender_is_valid(value):
                continue
            data[field] = value
        else:
            data[field] = value
        prefilled_fields.add(field)
    return data, prefilled_fields


def section_transition_reply(
    previous_section: str,
    current: dict,
    route: str,
    prefilled_fields: set[str] | None = None,
) -> str:
    prompt = current["prompt"]
    prefilled_fields = prefilled_fields or set()
    basic_fields = {"name", "gender", "birth_date", "blood_type"}
    history_fields = {
        "smoke",
        "chronic",
        "past_meds",
        "current_meds",
        "allergy",
    }
    if previous_section == current["section"]:
        return prompt
    if current["section"] == "basic":
        return patient_message("section.basic", prompt=prompt)
    if current["section"] == "history":
        if basic_fields.issubset(prefilled_fields):
            return patient_message("section.history_prefilled_basic", prompt=prompt)
        return patient_message("section.history", prompt=prompt)
    if current["section"] == "disease":
        route_label = ROUTE_LABELS.get(route) or patient_message("label.symptom")
        if basic_fields.issubset(prefilled_fields):
            message_key = (
                "section.disease_prefilled_all"
                if history_fields.issubset(prefilled_fields)
                else "section.disease_prefilled_basic"
            )
            return patient_message(message_key, route_label=route_label, prompt=prompt)
        return patient_message("section.disease", route_label=route_label, prompt=prompt)
    return prompt


def complaint_routes(data: dict, primary_route: str) -> list[str]:
    """Keep every evidenced supported symptom, with the primary route first."""
    assessed = data.get("_chief_assessment", {}).get("route_priority", [])
    routes = [route for route in [primary_route, *assessed] if route in SUPPORTED_PATIENT_ROUTES]
    return list(dict.fromkeys(routes))


def copy_prefills_to_secondary_routes(session: dict, questionnaire: list[dict]) -> None:
    """Reuse imported disease history without collapsing route-scoped answers."""
    data = session["data"]
    prefilled = set(session.get("prefilled_fields", []))
    for item in questionnaire:
        field = item["field"]
        base_field = item.get("base_field", field)
        if field == base_field or base_field not in prefilled or base_field not in data:
            continue
        data[field] = data[base_field]
        prefilled.add(field)
    session["prefilled_fields"] = sorted(prefilled)


def apply_chief_questionnaire_prefills(data: dict, questionnaire: list[dict]) -> None:
    """Skip questions whose route-scoped answer was explicit in the chief complaint."""
    extraction = data.get("_chief_assessment", {}).get("extraction")
    if not extraction:
        return
    try:
        assessment = ChiefComplaintAssessment.model_validate(extraction)
    except Exception:
        return
    data.update(
        questionnaire_prefills_from_assessment(
            assessment,
            questionnaire,
        )
    )
    for index, item in enumerate(questionnaire):
        questionnaire[index] = filter_question_by_questionnaire_answers(
            item,
            assessment.questionnaire_answers,
        )


def amie_initial_session(req: ChatRequest) -> dict:
    data, prefilled_fields = prefilled_patient_data(req)
    return {
        "session_id": req.session_id,
        "engine": "amie",
        "step": 0,
        "index": 0,
        "turn_count": 0,
        "triage_level": "routine",
        "questionnaire": list(CHIEF_QUESTIONNAIRE),
        "data": data,
        "prefilled_fields": sorted(prefilled_fields),
        "amie_state": {},
        "transcript": [],
        "ts": time.time(),
    }
