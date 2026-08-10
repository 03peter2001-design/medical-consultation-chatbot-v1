"""Every approved route must be able to finish its own questionnaire.

A route that cannot reach ``complete`` wastes the patient's answers and lands on
a clinician anyway, so each failure mode here is a governance defect rather than
a tuning problem. The interview is driven end to end because the defects this
guards against (unaskable required fields, turn budgets shorter than the
questionnaire) only appear after many turns.
"""

import json
import unittest

from amie.engine import AMIEEngine
from domain.questionnaires import (
    CANDIDATE_DISEASE_ROUTES,
    DISEASE_ROUTES,
    build_questionnaire,
    condition_matches,
    load_questionnaire_category,
)

BASIC_PREFILL = ("name", "gender", "birth_date", "blood_type")
HISTORY_PREFILL = ("smoke", "chronic", "past_meds", "current_meds", "allergy")

# Route entry governance diverts these before a questionnaire ever starts, but
# the questionnaires still exist and must stay finishable on their own terms.
GENDER_BY_SCENARIO = {"男性", "女性"}


class SilentExtractorLLM:
    """Return a valid but empty extraction so no facts are invented."""

    def generate_text(self, messages, **kwargs):
        return json.dumps(
            {
                "primary_symptom": "unknown",
                "primary_evidence": "",
                "symptom_domains": [],
                "onset": {"value": "unknown", "evidence": ""},
                "severity": {"value": "unknown", "evidence": ""},
                "is_new_or_changed": {"value": "unknown", "evidence": ""},
                "findings": [],
                "negated_findings": [],
                "route_candidates": [],
                "uncertain_fields": [],
            },
            ensure_ascii=False,
        )


def _answer_for(question: dict) -> str:
    kind = question.get("kind")
    if kind == "choice":
        options = question.get("options") or []
        return options[0] if options else "無"
    if kind == "duration":
        quick_options = question.get("quick_options") or []
        return quick_options[0] if quick_options else "1天"
    if kind == "date":
        return "1980-01-01"
    return "無"


def run_interview(route: str, *, gender: str, prefilled: tuple[str, ...]) -> dict:
    """Answer every question the engine asks until it stops asking."""
    engine = AMIEEngine(SilentExtractorLLM())
    questionnaire = build_questionnaire([route])
    data = {"type": route, "types": [route], "gender": gender}
    prefilled_fields = {*prefilled, "gender"}
    for field in prefilled_fields:
        data.setdefault(field, "已填")

    current = questionnaire[0]
    field = "reason"
    answer = "測試主訴"
    turn = 0
    asked: list[str] = []
    # The questionnaire is finite, so any run longer than it is a planner loop.
    limit = len(questionnaire) + 5
    while turn <= limit:
        turn += 1
        result = engine.run_turn(
            route=current.get("route") or route,
            answer=answer,
            current_field=field,
            data=data,
            questionnaire=questionnaire,
            prefilled_fields=prefilled_fields,
            turn_count=turn,
            previous_state=None,
        )
        data = result.data
        if result.action != "ask":
            return {
                "action": result.action,
                "triage_level": result.triage_level,
                "handoff_reason": result.handoff_reason,
                "turns": turn,
                "asked": asked,
                "questions": len(questionnaire),
            }
        current = result.next_question
        field = current["field"]
        answer = _answer_for(current)
        data[field] = answer
        asked.append(field)
    return {
        "action": "loop",
        "triage_level": "",
        "handoff_reason": f"超過 {limit} 輪仍未結束",
        "turns": turn,
        "asked": asked,
        "questions": len(questionnaire),
    }


class RouteCompletionTests(unittest.TestCase):
    def test_every_route_completes_with_and_without_record_prefill(self):
        scenarios = {
            "walk-in": (),
            "record-prefilled": BASIC_PREFILL + HISTORY_PREFILL,
        }
        for route in sorted(DISEASE_ROUTES):
            for gender in sorted(GENDER_BY_SCENARIO):
                for label, prefilled in scenarios.items():
                    with self.subTest(route=route, gender=gender, scenario=label):
                        outcome = run_interview(
                            route,
                            gender=gender,
                            prefilled=prefilled,
                        )
                        self.assertEqual(
                            outcome["action"],
                            "complete",
                            f"{route}／{gender}／{label} 在第 {outcome['turns']} 輪以 "
                            f"{outcome['action']} 結束（共 {outcome['questions']} 題，"
                            f"已答 {len(outcome['asked'])} 題）："
                            f"{outcome['handoff_reason']}",
                        )

    def test_candidate_gender_branches_remain_valid_but_cannot_enter_runtime(self):
        """Candidate schema stays reviewable without becoming a patient flow."""
        route = "genitourinary_system_problems"
        self.assertIn(route, CANDIDATE_DISEASE_ROUTES)
        questions = load_questionnaire_category(route)
        for gender in ("男性", "女性"):
            with self.subTest(gender=gender):
                opposite = "_female" if gender == "男性" else "_male"
                self.assertFalse(
                    [
                        item["field"]
                        for item in questions
                        if item["field"].endswith(opposite)
                        and condition_matches(item, {"gender": gender})
                    ],
                    f"{gender} 不應被問到 {opposite} 專屬題目",
                )
        with self.assertRaisesRegex(ValueError, "不支援"):
            build_questionnaire(route)

    def test_turn_budget_is_never_shorter_than_the_questionnaire(self):
        """A route may not run out of turns before its own questions are done."""
        undersized = []
        for route in sorted(DISEASE_ROUTES):
            outcome = run_interview(route, gender="男性", prefilled=())
            if "輪數上限" in outcome["handoff_reason"]:
                undersized.append(f"{route}（{outcome['questions']} 題）")
        self.assertFalse(
            undersized,
            f"下列路由的題目數超過輪數上限，一般掛號病人永遠無法完診：{undersized}",
        )


if __name__ == "__main__":
    unittest.main()
