"""Session and questionnaire preparation helpers for patient interviews."""

import time

from amie.clinical_facts import (
    filter_question_by_questionnaire_answers,
    questionnaire_prefills_from_assessment,
)
from amie.models import ChiefComplaintAssessment
from amie.rule_config import load_safety_rules
from app.models import ChatRequest
from app.services.input_validation import prefill_gender_is_valid
from domain.questionnaires import CHIEF_QUESTIONNAIRE, ROUTE_LABELS, parse_birth_date
from domain.terminology_reference import filter_supported_codings

ROUTE_KEYWORDS = load_safety_rules()["route_keywords"]
SUPPORTED_PATIENT_ROUTES = frozenset(ROUTE_KEYWORDS)
URGENT_CONDITION_CANDIDATES = load_safety_rules()["urgent_condition_candidates"]


def route_keyword_hits(text: str) -> dict[str, bool]:
    return {
        route: any(keyword in text for keyword in keywords)
        for route, keywords in ROUTE_KEYWORDS.items()
    }


def local_complaint_route(text: str) -> str | None:
    """Return a route only when deterministic keywords are unambiguous."""
    hits = route_keyword_hits(text)
    matched = [route for route, is_match in hits.items() if is_match]
    return matched[0] if len(matched) == 1 else None


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
        return f"主訴已記錄。接下來填寫基本資料。\n\n{prompt}"
    if current["section"] == "history":
        if basic_fields.issubset(prefilled_fields):
            return f"主訴已記錄，基本資料已從病歷帶入。接下來補充尚未取得的病史。\n\n{prompt}"
        return f"基本資料完成。接下來了解一般病史。\n\n{prompt}"
    if current["section"] == "disease":
        if basic_fields.issubset(prefilled_fields):
            imported = "基本資料與病史" if history_fields.issubset(prefilled_fields) else "基本資料"
            return (
                f"已從病歷帶入{imported}。接下來進入"
                f"{ROUTE_LABELS.get(route, '症狀')}問卷。\n\n{prompt}"
            )
        return f"病史資料完成。接下來進入{ROUTE_LABELS.get(route, '症狀')}問卷。\n\n{prompt}"
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
