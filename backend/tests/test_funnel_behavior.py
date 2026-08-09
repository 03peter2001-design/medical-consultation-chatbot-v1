"""Behavioural guards on how the funnel narrows, stops, and stays scoped.

Each test here pins a decision the funnel used to get wrong: completing on
denials alone, confirming its own leader, letting one complaint's answers score
another complaint's diseases, or losing a domain's red flags because the patient
used a different word for the same anatomy.
"""

import json
import unittest

from amie.clinical_facts import fact_conflicts, facts_for_route
from amie.disease_profiles import question_fact_codes, score_diseases
from amie.engine import AMIEEngine
from amie.safety import detect_red_flags
from domain.questionnaires import (
    CANDIDATE_DISEASE_ROUTES,
    ROUTE_DISPOSITIONS,
    ROUTE_KEYWORDS,
    build_questionnaire,
    clinical_domain,
    load_questionnaire_category,
    load_questionnaire_policy,
)

DISPOSITION_SEVERITY = {"questionnaire": 0, "handoff": 1, "urgent": 2}

# Two longer keywords legitimately name a different condition than the shorter
# one they contain, so the specificity heuristic is right to prefer them.
ALLOWED_DISPOSITION_DOWNGRADES = set()


def fact(code, status="present", *, route="", evidence="測試"):
    return {
        "code": code,
        "status": status,
        "evidence": evidence,
        "source": "test",
        "turn": 1,
        "route": route,
    }


class StubLLM:
    def generate_text(self, messages, **kwargs):
        return json.dumps({"primary_symptom": "unknown"}, ensure_ascii=False)


class DenialScoringTests(unittest.TestCase):
    """H2: denying everything must not read as having covered everything."""

    def test_denials_raise_coverage_but_not_decisive_coverage(self):
        codes = [
            "chest_pressure",
            "exertional_trigger",
            "diaphoresis",
            "nausea",
            "syncope",
            "reproducible_tenderness",
        ]
        assessment = score_diseases([fact(code, "absent") for code in codes], route="chest")
        acs = next(item for item in assessment["ranked"] if item["id"] == "acute_coronary_syndrome")
        self.assertEqual(acs["coverage"], 1.0)
        self.assertEqual(acs["decisive_coverage"], 0.0)
        self.assertEqual(acs["net_votes"], 0)

    def test_must_not_miss_outranks_a_benign_look_alike_at_equal_votes(self):
        assessment = score_diseases([], route="chest")
        tied = [item for item in assessment["ranked"] if item["net_votes"] == 0]
        killers = [index for index, item in enumerate(tied) if item["must_not_miss"]]
        benign = [index for index, item in enumerate(tied) if not item["must_not_miss"]]
        self.assertTrue(killers and benign)
        self.assertLess(max(killers), min(benign), "不能漏診疾病必須排在同票的良性鑑別之前")


class CompletionGateTests(unittest.TestCase):
    """H4: an unasked killer is not a ruled-out killer."""

    def setUp(self):
        self.questionnaire = build_questionnaire("chest")
        self.engine = AMIEEngine(StubLLM())

    def test_interview_stays_open_while_a_killer_has_askable_clues_left(self):
        data = {
            "type": "chest",
            "types": ["chest"],
            "reason": "胸口悶",
            "_clinical_facts": [fact("chest_pressure", route="chest")],
        }
        result = self.engine.run_turn(
            route="chest",
            answer="感覺有重物壓迫",
            current_field="quality",
            data=data,
            questionnaire=self.questionnaire,
            prefilled_fields={"name", "gender", "birth_date", "blood_type"},
            turn_count=2,
        )
        self.assertEqual(result.action, "ask")
        self.assertTrue(result.decision["must_not_miss_gap"])


class RouteScopeTests(unittest.TestCase):
    """H5/H6: one complaint's answers must not score another's diseases."""

    def test_a_chest_scoped_fact_does_not_reach_the_abdomen_table(self):
        facts = [fact("onset_sudden", route="chest")]
        self.assertIn("onset_sudden", facts_for_route(facts, "chest"))
        self.assertNotIn("onset_sudden", facts_for_route(facts, "abdomen"))

    def test_an_unscoped_fact_still_applies_everywhere(self):
        facts = [fact("onset_sudden")]
        self.assertIn("onset_sudden", facts_for_route(facts, "chest"))
        self.assertIn("onset_sudden", facts_for_route(facts, "abdomen"))

    def test_scoring_follows_the_session_route_not_the_current_question(self):
        engine = AMIEEngine(StubLLM())
        questionnaire = build_questionnaire(["chest", "abdomen"])
        data = {
            "type": "chest",
            "types": ["chest", "abdomen"],
            "reason": "胸口悶又肚子痛",
            "_clinical_facts": [fact("chest_pressure", route="chest")],
        }
        # The abdominal question is on screen, but the differential must still
        # be the session's primary (chest) table.
        result = engine.run_turn(
            route="abdomen",
            answer="輕微",
            current_field="abdomen_severity",
            data=data,
            questionnaire=questionnaire,
            prefilled_fields={"name", "gender", "birth_date", "blood_type"},
            turn_count=3,
        )
        ranked_ids = {item["id"] for item in result.disease_assessment.get("ranked", [])}
        self.assertIn("acute_coronary_syndrome", ranked_ids)
        self.assertNotIn("appendicitis", ranked_ids)

    def test_a_changed_answer_is_reported_instead_of_silently_overwritten(self):
        earlier = [fact("onset_sudden", "present", route="chest", evidence="突然發作")]
        later = [fact("onset_sudden", "absent", route="chest", evidence="其實是慢慢來的")]
        conflicts = fact_conflicts(earlier, later)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["previous_status"], "present")
        self.assertEqual(conflicts[0]["current_status"], "absent")
        self.assertEqual(conflicts[0]["route"], "chest")

    def test_the_same_code_on_two_routes_is_not_a_conflict(self):
        earlier = [fact("onset_sudden", "present", route="chest")]
        later = [fact("onset_sudden", "absent", route="abdomen")]
        self.assertEqual(fact_conflicts(earlier, later), [])


class ClinicalDomainTests(unittest.TestCase):
    """Unreviewed clinical-domain mappings must stay outside runtime."""

    def test_candidate_route_cannot_borrow_a_runtime_clinical_domain(self):
        answer = "撕裂樣胸痛，而且冒冷汗"
        chest_flags = {flag["code"] for flag in detect_red_flags("chest", answer, {})}
        candidate_flags = {
            flag["code"] for flag in detect_red_flags("cardiovascular_issues", answer, {})
        }
        self.assertIn("cardiovascular_issues", CANDIDATE_DISEASE_ROUTES)
        self.assertIsNone(clinical_domain("cardiovascular_issues"))
        self.assertTrue(candidate_flags < chest_flags)
        with self.assertRaisesRegex(ValueError, "不支援"):
            build_questionnaire("cardiovascular_issues")


class RouteGovernanceTests(unittest.TestCase):
    """N5: the specificity heuristic may escalate a route, never soften one."""

    def test_a_longer_keyword_never_downgrades_a_stricter_route(self):
        downgrades = set()
        for loose, loose_keywords in ROUTE_KEYWORDS.items():
            for strict, strict_keywords in ROUTE_KEYWORDS.items():
                if (
                    DISPOSITION_SEVERITY[ROUTE_DISPOSITIONS[loose]]
                    >= DISPOSITION_SEVERITY[ROUTE_DISPOSITIONS[strict]]
                ):
                    continue
                for loose_keyword in loose_keywords:
                    for strict_keyword in strict_keywords:
                        if strict_keyword.casefold() in loose_keyword.casefold() and len(
                            loose_keyword
                        ) > len(strict_keyword):
                            downgrades.add((strict, loose))
        self.assertEqual(
            downgrades,
            ALLOWED_DISPOSITION_DOWNGRADES,
            "新關鍵字讓較嚴格的路由被較寬鬆的路由蓋過，需重新檢視 disposition",
        )

    def test_every_route_in_a_clinical_domain_names_a_route_that_owns_a_table(self):
        for route in ROUTE_KEYWORDS:
            domain = clinical_domain(route)
            if domain is None:
                continue
            with self.subTest(route=route):
                self.assertIn(domain, {"chest", "headache", "abdomen"})


class GeneralHistoryRetentionTests(unittest.TestCase):
    """General history can be dropped purely because of what the patient answered.

    ``smoke``, ``chronic`` and ``past_meds`` are not in any route's
    ``required_fields`` and produce no clinical fact, so ``question_utility``
    rates them at zero. They are therefore asked only while the interview happens
    to still be running: a traversal that satisfies the funnel early completes
    without ever asking a chest-pain patient whether they smoke.

    This pins the behaviour so it cannot silently spread to more fields. The fix
    is clinical policy (route ``required_fields``) and is recorded in
    ``docs/funnel_clinical_signoff.md``.
    """

    DROPPABLE_HISTORY = {"smoke", "chronic", "past_meds"}
    KNOWN_OPTIONAL_ZERO_STATIC_UTILITY = {*DROPPABLE_HISTORY, "chronic_detail"}

    def _asked_fields(self, route, option_index):
        engine = AMIEEngine(StubLLM())
        questionnaire = build_questionnaire([route])
        data = {"type": route, "types": [route], "gender": "男性"}
        current, field, answer = questionnaire[0], "reason", "測試主訴"
        asked = []
        for turn in range(1, len(questionnaire) + 6):
            result = engine.run_turn(
                route=route,
                answer=answer,
                current_field=field,
                data=data,
                questionnaire=questionnaire,
                prefilled_fields={"gender"},
                turn_count=turn,
                previous_state=None,
            )
            data = result.data
            if result.action != "ask":
                return result.action, asked
            current = result.next_question
            field = current["field"]
            options = current.get("options") or []
            if options:
                answer = options[option_index]
            elif current.get("kind") == "duration":
                answer = (current.get("quick_options") or ["1天"])[0]
            elif current.get("kind") == "date":
                answer = "1980-01-01"
            else:
                answer = "無"
            data[field] = answer
            asked.append(field)
        return "loop", asked

    def test_answer_choice_alone_decides_whether_smoking_is_ever_asked(self):
        action_first, asked_first = self._asked_fields("chest", 0)
        action_last, asked_last = self._asked_fields("chest", -1)
        self.assertEqual(action_first, "complete")
        self.assertEqual(action_last, "complete")
        self.assertTrue(self.DROPPABLE_HISTORY <= set(asked_first))
        self.assertFalse(
            self.DROPPABLE_HISTORY & set(asked_last),
            "此 traversal 原本就不應問到一般病史；行為若改變請一併更新 signoff 文件",
        )

    def test_only_known_history_fields_are_optional_with_zero_static_utility(self):
        """Prevent the same silent drop from spreading to another history field."""
        history = load_questionnaire_category("history")
        for route in ("chest", "abdomen", "headache"):
            with self.subTest(route=route):
                required = set(load_questionnaire_policy(route)["required_fields"])
                droppable = {
                    item["field"]
                    for item in history
                    if item["field"] not in required and not question_fact_codes(item)
                }
                self.assertEqual(droppable, self.KNOWN_OPTIONAL_ZERO_STATIC_UTILITY)


if __name__ == "__main__":
    unittest.main()
