"""Validated clinical facts shared by safety, scoring, and audit output."""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from .models import ChiefComplaintAssessment, QuestionnaireAnswerEvidence
from .rule_config import clinical_fact_codes, clinical_fact_rules

FACT_CODES = frozenset(clinical_fact_codes())


def normalize_fact(raw: Any) -> dict[str, Any] | None:
    """Return a bounded fact or reject values outside the deployed vocabulary."""
    rules = clinical_fact_rules()
    allowed_fields = set(rules["record_fields"])
    # ``route`` was added after the first sessions were persisted, so records
    # without it stay valid and are treated as applying to every route.
    if not isinstance(raw, dict) or set(raw) not in (
        allowed_fields,
        allowed_fields - {"route"},
    ):
        return None
    code = str(raw.get("code", "")).strip()
    status = str(raw.get("status", "present")).strip().lower()
    evidence = str(raw.get("evidence", "")).strip()[:160]
    source = str(raw.get("source", "semantic")).strip()[:40] or "semantic"
    route = str(raw.get("route", "") or "").strip()[:64]
    try:
        turn = max(0, int(raw.get("turn", 0)))
    except (TypeError, ValueError):
        turn = 0
    if code not in FACT_CODES or status not in set(rules["statuses"]) or not evidence:
        return None
    return {
        "code": code,
        "status": status,
        "evidence": evidence,
        "source": source,
        "turn": turn,
        "route": route,
    }


def fact_key(fact: dict[str, Any]) -> tuple[str, str]:
    return (fact.get("route", ""), fact["code"])


def facts_for_route(
    facts: Iterable[dict[str, Any]] | None,
    route: str,
) -> dict[str, dict[str, Any]]:
    """Index facts by code for one route, route-scoped evidence winning.

    Codes such as ``onset_sudden`` are shared by several disease tables, so an
    answer given about the chest must not be read as an answer about the
    abdomen. Facts with no route are unscoped and apply everywhere.
    """
    indexed: dict[str, dict[str, Any]] = {}
    for fact in merge_facts([], facts):
        fact_route = fact.get("route", "")
        if fact_route and fact_route != route:
            continue
        if fact_route or fact["code"] not in indexed:
            indexed[fact["code"]] = fact
    return indexed


def merge_facts(
    existing: Iterable[dict[str, Any]] | None,
    incoming: Iterable[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Merge facts deterministically; newer explicit evidence wins per route."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in [*(existing or []), *(incoming or [])]:
        fact = normalize_fact(raw)
        if fact:
            merged[fact_key(fact)] = fact
    return [merged[key] for key in sorted(merged)]


def fact_conflicts(
    existing: Iterable[dict[str, Any]] | None,
    incoming: Iterable[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Report facts the patient has just contradicted.

    The merge keeps the newer answer, which is usually the right call, but a
    silent overwrite hides the two cases that matter: the patient corrected
    themselves, or the extractor got it wrong the first time. Either way a
    clinician has to see that the record changed.
    """
    previous = {fact_key(fact): fact for fact in merge_facts([], existing)}
    conflicts = []
    for fact in merge_facts([], incoming):
        earlier = previous.get(fact_key(fact))
        if earlier is None or earlier["status"] == fact["status"]:
            continue
        conflicts.append(
            {
                "code": fact["code"],
                "route": fact.get("route", ""),
                "previous_status": earlier["status"],
                "previous_evidence": earlier["evidence"],
                "current_status": fact["status"],
                "current_evidence": fact["evidence"],
                "turn": fact["turn"],
            }
        )
    return conflicts


def facts_from_assessment(
    assessment: ChiefComplaintAssessment,
    *,
    turn: int,
    source: str,
    route: str = "",
) -> list[dict[str, Any]]:
    """Convert the evidence-grounded semantic extraction into fact records."""
    facts: list[dict[str, Any]] = []
    scalar_codes = clinical_fact_rules()["scalar_mappings"]
    for field, mapping in scalar_codes.items():
        value = getattr(assessment, field)
        code = mapping.get(value.value)
        if code and value.evidence:
            facts.append(
                {
                    "code": code,
                    "status": "present",
                    "evidence": value.evidence,
                    "source": source,
                    "turn": turn,
                    "route": route,
                }
            )
    symptom_mappings = clinical_fact_rules()["symptom_mappings"]
    for symptom in assessment.symptoms:
        code = symptom_mappings.get(symptom.code)
        if code and symptom.evidence:
            facts.append(
                {
                    "code": code,
                    "status": "present",
                    "evidence": symptom.evidence,
                    "source": source,
                    "turn": turn,
                    "route": route,
                }
            )
    for finding in [*assessment.findings, *assessment.negated_findings]:
        facts.append(
            {
                "code": finding.code,
                "status": finding.status,
                "evidence": finding.evidence,
                "source": source,
                "turn": turn,
                "route": route,
            }
        )
    return merge_facts([], facts)


def questionnaire_prefills_from_assessment(
    assessment: ChiefComplaintAssessment,
    questionnaire: Iterable[dict[str, Any]],
    *,
    route_hint: str | None = None,
) -> dict[str, str]:
    """Map explicit, symptom-scoped facts onto matching questionnaire fields.

    Model answers are allowlisted against the deployed questionnaire before
    reaching this function. Typed semantic facts continue to resolve choice
    options through ``filter_question_by_known_facts``.
    """
    questions = list(questionnaire)
    prefills: dict[str, str] = {}
    for answer in assessment.questionnaire_answers:
        for item in questions:
            if item.get("route") != answer.route or item.get("base_field") != answer.field:
                continue
            selected = answer.value.split("、")
            is_complete = not item.get("multiple") or (
                bool(selected) and set(selected).issubset(set(item.get("exclusive_options", [])))
            )
            if is_complete:
                prefills[item["field"]] = answer.value
    routes: list[str] = list(
        dict.fromkeys(
            str(item["route"])
            for item in questions
            if item.get("route") and item.get("base_field") == "onset"
        )
    )
    scoped_times: dict[str, str] = {
        item.route: item.onset_time.value
        for item in assessment.symptom_assessments
        if item.route in routes and item.onset_time.value != "unknown"
    }
    if (
        len(routes) == 1
        and assessment.primary_symptom == routes[0]
        and assessment.onset_time.value != "unknown"
    ):
        scoped_times.setdefault(routes[0], assessment.onset_time.value)
    elif route_hint in routes and assessment.onset_time.value != "unknown":
        scoped_times.setdefault(str(route_hint), assessment.onset_time.value)

    for item in questions:
        if item.get("base_field") == "onset" and item.get("route") in scoped_times:
            prefills.setdefault(item["field"], scoped_times[item["route"]])
    return prefills


def filter_question_by_questionnaire_answers(
    question: dict[str, Any],
    answers: Iterable[QuestionnaireAnswerEvidence] | None,
) -> dict[str, Any]:
    """Remove known partial selections without completing a multiple-choice field."""
    filtered = deepcopy(question)
    if not filtered.get("multiple"):
        return filtered
    known = {
        selected
        for answer in answers or []
        if (
            answer.route == filtered.get("route")
            and answer.field == filtered.get("base_field", filtered.get("field"))
        )
        for selected in answer.value.split("、")
    }
    if not known:
        return filtered
    filtered["options"] = [option for option in filtered.get("options", []) if option not in known]
    filtered["semantic_options"] = {
        option: mapping
        for option, mapping in filtered.get("semantic_options", {}).items()
        if option not in known
    }
    filtered["exclusive_options"] = [
        option for option in filtered.get("exclusive_options", []) if option in filtered["options"]
    ]
    return filtered


def facts_from_legacy_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Reconstruct conservative facts from stored questionnaires without an LLM."""
    existing_facts = data.get("_clinical_facts", [])
    # An explicit fact stream is authoritative. Mixing it with reconstruction
    # from unscoped legacy fields would duplicate route-scoped live answers and
    # leak the primary questionnaire into secondary disease tables.
    if existing_facts:
        return merge_facts([], existing_facts)

    rules = clinical_fact_rules()
    text = "、".join(
        str(data.get(field, "")) for field in rules["legacy_text_fields"] if data.get(field)
    )
    facts = [
        {
            "code": code,
            "status": "present",
            "evidence": term,
            "source": "legacy_questionnaire",
            "turn": 0,
            "route": "",
        }
        for code, terms in rules["legacy_terms"].items()
        for term in terms
        if term in text
    ]
    for field_rule in rules["legacy_field_rules"]:
        value = str(data.get(field_rule["field"], "")).strip()
        values = field_rule["values"]
        matched = (
            any(candidate in value for candidate in values)
            if field_rule["match"] == "contains_any"
            else value in values
        )
        if not matched:
            continue
        facts.append(
            {
                "code": field_rule["code"],
                "status": field_rule["status"],
                "evidence": (
                    value if field_rule["evidence"] == "$value" else field_rule["evidence"]
                ),
                "source": "legacy_questionnaire",
                "turn": 0,
                "route": "",
            }
        )
    semantic = data.get("_semantic_safety_state") or data.get("_chief_assessment", {}).get(
        "extraction"
    )
    if semantic:
        try:
            assessment = ChiefComplaintAssessment.model_validate(semantic)
            facts.extend(
                facts_from_assessment(
                    assessment,
                    turn=0,
                    source="legacy_semantic",
                )
            )
        except Exception:
            pass
    return merge_facts(existing_facts, facts)


def filter_question_by_known_facts(
    question: dict[str, Any],
    facts: Iterable[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Hide choice options already resolved by evidence-grounded facts."""
    filtered = deepcopy(question)
    if filtered.get("kind") != "choice":
        return filtered

    known = {
        code: fact["status"]
        for code, fact in facts_for_route(facts, str(filtered.get("route") or "")).items()
    }
    if not known:
        return filtered

    options = list(filtered.get("options", []))
    semantic_options = deepcopy(filtered.get("semantic_options", {}))
    exclusive = set(filtered.get("exclusive_options", []))
    scalar_mappings = clinical_fact_rules()["scalar_mappings"]
    remaining: list[str] = []

    for option in options:
        if option in exclusive:
            continue
        mapping = semantic_options.get(option)
        if not isinstance(mapping, dict):
            remaining.append(option)
            continue

        mapped_codes = {
            *mapping.get("findings", []),
            *mapping.get("negated_findings", []),
        }
        scalar_resolution_codes: set[str] = set()
        for field, values in scalar_mappings.items():
            code = values.get(mapping.get(field))
            if code:
                mapped_codes.add(code)
                scalar_resolution_codes.update(values.values())
        resolution_codes = (
            set(mapping.get("resolution_facts", [])) or scalar_resolution_codes or mapped_codes
        )
        mode = mapping.get(
            "resolved_when",
            "any" if scalar_resolution_codes else "all",
        )
        resolved = bool(resolution_codes) and (
            bool(resolution_codes & known.keys())
            if mode == "any"
            else resolution_codes.issubset(known)
        )
        if resolved:
            semantic_options.pop(option, None)
            continue

        cleaned = {
            key: value
            for key, value in mapping.items()
            if key not in {"resolution_facts", "resolved_when"}
        }
        for key in ("findings", "negated_findings"):
            if key in cleaned:
                unresolved = [code for code in cleaned[key] if code not in known]
                if unresolved:
                    cleaned[key] = unresolved
                else:
                    cleaned.pop(key)
        semantic_options[option] = cleaned
        remaining.append(option)

    exclusive_options = [option for option in options if option in exclusive]
    for option in exclusive_options:
        mapping = semantic_options.get(option)
        if not isinstance(mapping, dict):
            continue
        cleaned = {
            key: value
            for key, value in mapping.items()
            if key not in {"resolution_facts", "resolved_when"}
        }
        for key in ("findings", "negated_findings"):
            if key in cleaned:
                unresolved = [code for code in cleaned[key] if code not in known]
                if unresolved:
                    cleaned[key] = unresolved
                else:
                    cleaned.pop(key)
        if cleaned:
            semantic_options[option] = cleaned
        else:
            semantic_options.pop(option, None)

    if not remaining:
        return None
    filtered["options"] = [*remaining, *exclusive_options]
    filtered["exclusive_options"] = exclusive_options
    filtered["semantic_options"] = {
        option: mapping
        for option, mapping in semantic_options.items()
        if option in filtered["options"]
    }
    return filtered
