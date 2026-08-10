"""Measure interview length under a proposed question-batching change.

Batching several questions onto one page trades away adaptivity: the funnel can
no longer let the first answer cancel the rest. Whether that trade is worth
making depends on two numbers that cannot be reasoned out in advance — how many
turns batching removes, and how many extra questions the patient answers because
the funnel was not allowed to skip them. This script produces both.

The batch groups below are the *proposal under evaluation*, deliberately kept out
of the questionnaire data so that measuring a change does not also make it.

Answers are synthetic and deterministic (always the first offered option), which
is a stated assumption, not a claim about real patients: it fixes one traversal
of the funnel so baseline and batched runs are comparable. Results therefore
describe this traversal only.

Usage (from backend/):
    venv/bin/python scripts/measure_interview_length.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from amie.engine import AMIEEngine  # noqa: E402
from domain.questionnaires import DISEASE_ROUTES, build_questionnaire  # noqa: E402

# The proposal: present these route-scoped fields together on one page.
PROPOSED_BATCHES: dict[str, tuple[tuple[str, ...], ...]] = {
    "chest": (("quality", "aggravate", "relieve"),),
    "abdomen": (("quality", "aggravate", "relieve"),),
    "headache": (("quality", "aggravate", "relieve"),),
}
BASIC_PREFILL = ("name", "gender", "birth_date", "blood_type")
HISTORY_PREFILL = ("smoke", "chronic", "past_meds", "current_meds", "allergy")


class SilentExtractorLLM:
    """Extract nothing, so only structured options drive the funnel."""

    def generate_text(self, messages, **kwargs):
        return json.dumps({"primary_symptom": "unknown"}, ensure_ascii=False)


def _answer_for(question: dict) -> str:
    kind = question.get("kind")
    if kind == "choice":
        options = question.get("options") or []
        return options[0] if options else "無"
    if kind == "duration":
        quick = question.get("quick_options") or []
        return quick[0] if quick else "1天"
    if kind == "date":
        return "1980-01-01"
    return "無"


def _batch_for(route: str, field: str, questionnaire: list[dict]) -> list[dict]:
    """Return every question shown on the same page as ``field``."""
    by_field = {item["field"]: item for item in questionnaire}
    base = by_field.get(field, {}).get("base_field", field)
    for group in PROPOSED_BATCHES.get(route, ()):
        if base not in group:
            continue
        return [
            item
            for item in questionnaire
            if item.get("base_field", item["field"]) in group
            and item.get("route") == by_field.get(field, {}).get("route")
        ]
    return [by_field[field]] if field in by_field else []


def _summary(*, screens: int, answered: list[str], action: str, data: dict) -> dict:
    return {
        "screens": screens,
        "answered": len(answered),
        "action": action,
        "fields": answered,
        # This is not printed as an outcome measure. It makes the simulator's
        # core validity testable: every submitted structured answer must pass
        # through the same fact extraction as the live sequential flow.
        "clinical_fact_codes": sorted(
            {
                str(item.get("code"))
                for item in data.get("_clinical_facts") or []
                if item.get("code")
            }
        ),
    }


def run(route: str, *, prefilled: tuple[str, ...], batched: bool) -> dict:
    engine = AMIEEngine(SilentExtractorLLM())
    questionnaire = build_questionnaire([route])
    data = {"type": route, "types": [route], "gender": "男性"}
    prefilled_fields = {*prefilled, "gender"}
    for name in prefilled_fields:
        data.setdefault(name, "已填")

    page = [questionnaire[0]]
    screens = 0
    answered: list[str] = []
    previous_state: dict = {}
    while screens <= len(questionnaire) + 5:
        screens += 1
        # A proposed page submits all of its answers together. Feed every one
        # through ``run_turn`` so structured options still produce facts; merely
        # pre-populating ``data`` would make the planner skip the fields while
        # silently discarding their clinical meaning. All answers on the page
        # share a turn number because the metric counts patient-facing screens.
        result = None
        for current in page:
            field = current["field"]
            answer = "測試主訴" if field == "reason" else _answer_for(current)
            data[field] = answer
            if field != "reason":
                answered.append(field)
            result = engine.run_turn(
                route=current.get("route") or route,
                answer=answer,
                current_field=field,
                data=data,
                questionnaire=questionnaire,
                prefilled_fields=prefilled_fields,
                turn_count=screens,
                previous_state=previous_state,
            )
            data = result.data
            previous_state = {
                "triage_level": result.triage_level,
                "red_flags": result.red_flags,
                "differential_hypotheses": result.differential_hypotheses,
                "disease_assessment": result.disease_assessment,
                "clinical_facts": result.clinical_facts,
                "knowledge_gaps": result.knowledge_gaps,
                "evidence_timeline": result.evidence_timeline,
                "rag_sources": result.rag_sources,
            }

        if result is None:
            return _summary(screens=screens, answered=answered, action="loop", data=data)
        if result.action != "ask":
            return _summary(
                screens=screens,
                answered=answered,
                action=result.action,
                data=data,
            )
        current = result.next_question
        candidates = _batch_for(route, current["field"], questionnaire) if batched else [current]
        page = [item for item in candidates if item["field"] not in data]
    return _summary(screens=screens, answered=answered, action="loop", data=data)


def main() -> None:
    scenarios = {"walk-in": (), "record-prefilled": BASIC_PREFILL + HISTORY_PREFILL}
    routes = [route for route in ("chest", "abdomen", "headache") if route in DISEASE_ROUTES]
    header = f"{'route':10} {'scenario':17} {'screens':>16} {'questions answered':>20}"
    print(header)
    print("-" * len(header))
    for route in routes:
        for label, prefilled in scenarios.items():
            base = run(route, prefilled=prefilled, batched=False)
            batch = run(route, prefilled=prefilled, batched=True)
            screens = f"{base['screens']} → {batch['screens']}"
            asked = f"{base['answered']} → {batch['answered']}"
            print(f"{route:10} {label:17} {screens:>16} {asked:>20}")
            if base["action"] != "complete" or batch["action"] != "complete":
                print(f"{'':28} 未完診：{base['action']} / {batch['action']}")


if __name__ == "__main__":
    main()
