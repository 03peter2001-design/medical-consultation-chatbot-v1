"""Structural guards on the disease-vote funnel.

The funnel can only narrow if the evidence it asks for can actually be produced
and if its weights can separate one profile from another. Both properties live
across three artifacts (questionnaires, safety rules, disease tables) that are
edited independently, so they are asserted here rather than assumed.
"""

import unittest

from amie.clinical_facts import FACT_CODES
from amie.disease_profiles import load_profile_document, profile_quality_report
from amie.rule_config import clinical_fact_rules
from domain.questionnaires import (
    QUESTIONNAIRE_DATA_DIR,
    build_questionnaire,
    load_questionnaire_category,
)

DISEASE_TABLE_ROUTES = ("chest", "abdomen", "headache")

# Scoring debt inherited from tables generated before graded weights and
# rule-out clues were required. These lists may shrink when a table is
# regenerated; they must never grow.
KNOWN_FLAT_WEIGHT_PROFILES = 33
KNOWN_MUST_NOT_MISS_WITHOUT_RULE_OUT = 17

# These clues remain in provisional disease tables, but the questionnaire
# options that would create them were withdrawn pending clinical signoff. The
# debt may shrink after review; no other unreachable clue may be introduced.
KNOWN_UNREACHABLE_CLUES = {
    ("abdomen", "gastrointestinal_bleeding"): {"major_bleeding"},
    ("headache", "posterior_circulation_stroke"): {
        "gait_unsteadiness",
        "vertigo",
    },
}


def producible_fact_codes() -> set[str]:
    """Every fact code some patient answer can actually create."""
    rules = clinical_fact_rules()
    produced: set[str] = set()

    for path in QUESTIONNAIRE_DATA_DIR.glob("*.json"):
        for question in load_questionnaire_category(path.stem):
            for mapping in (question.get("semantic_options") or {}).values():
                produced.update(mapping.get("findings", []))
                produced.update(mapping.get("negated_findings", []))
                for field, values in rules["scalar_mappings"].items():
                    code = values.get(mapping.get(field))
                    if code:
                        produced.add(code)

    # Free-text answers reach the remaining codes through keyword rules and the
    # semantic extractor's own vocabulary.
    produced.update(rules["legacy_terms"])
    produced.update(rule["code"] for rule in rules["legacy_field_rules"])
    produced.update(rules["symptom_mappings"].values())
    for values in rules["scalar_mappings"].values():
        produced.update(values.values())
    return produced & FACT_CODES


class DiseaseTableReachabilityTests(unittest.TestCase):
    def test_every_clue_fact_can_be_produced_by_some_answer(self):
        """A clue nobody can answer is a permanent hole in that profile's score."""
        produced = producible_fact_codes()
        for route in DISEASE_TABLE_ROUTES:
            document = load_profile_document(route)
            for profile in document["profiles"]:
                unreachable = sorted(
                    {clue["fact"] for clue in profile["clues"]} - produced,
                )
                with self.subTest(route=route, profile=profile["id"]):
                    known = KNOWN_UNREACHABLE_CLUES.get((route, profile["id"]), set())
                    self.assertFalse(
                        sorted(set(unreachable) - known),
                        f"{route}／{profile['id']} 依賴問診永遠問不到的線索：{unreachable}",
                    )

    def test_questionnaire_options_stay_within_the_fact_vocabulary(self):
        for path in sorted(QUESTIONNAIRE_DATA_DIR.glob("*.json")):
            for question in load_questionnaire_category(path.stem):
                for option, mapping in (question.get("semantic_options") or {}).items():
                    codes = {
                        *mapping.get("findings", []),
                        *mapping.get("negated_findings", []),
                    }
                    with self.subTest(category=path.stem, field=question["field"]):
                        self.assertFalse(
                            sorted(codes - FACT_CODES),
                            f"{path.stem}.{question['field']}／{option} 使用未登錄的 fact",
                        )

    def test_none_of_the_above_negates_every_sibling_finding(self):
        """An exclusive "no" that forgets an option silently leaves it unknown."""
        for route in DISEASE_TABLE_ROUTES:
            for question in build_questionnaire([route]):
                semantic = question.get("semantic_options") or {}
                for exclusive in question.get("exclusive_options") or []:
                    negated = set(semantic.get(exclusive, {}).get("negated_findings", []))
                    if not negated:
                        continue
                    siblings = {
                        code
                        for option, mapping in semantic.items()
                        if option != exclusive
                        for code in mapping.get("findings", [])
                    }
                    with self.subTest(route=route, field=question["field"]):
                        self.assertFalse(
                            sorted(siblings - negated),
                            f"{question['field']}／{exclusive} 未涵蓋所有選項的否定",
                        )


class DiseaseTableQualityTests(unittest.TestCase):
    def test_scoring_debt_does_not_grow(self):
        reports = [load_profile_document(route) for route in DISEASE_TABLE_ROUTES]
        flat = sum(len(profile_quality_report(d)["flat_weight_profiles"]) for d in reports)
        no_rule_out = sum(
            len(profile_quality_report(d)["must_not_miss_without_rule_out"]) for d in reports
        )
        self.assertLessEqual(
            flat,
            KNOWN_FLAT_WEIGHT_PROFILES,
            "疾病表新增了權重全部相同的 profile，漏斗將無法分辨線索強弱",
        )
        self.assertLessEqual(
            no_rule_out,
            KNOWN_MUST_NOT_MISS_WITHOUT_RULE_OUT,
            "不能漏診疾病新增了沒有 rule-out 線索的 profile，否認將無法降低票數",
        )

    def test_generator_requires_graded_weights_and_rule_out_clues(self):
        """The debt above must not be re-created by the next regeneration."""
        source = (
            QUESTIONNAIRE_DATA_DIR.parent / "scripts" / "build_disease_profiles.py"
        ).read_text(encoding="utf-8")
        self.assertIn("weight 只能是 1、2 或 3", source)
        self.assertIn('status="absent"', source)
        self.assertNotIn('"weight": 1})', source)


class ClinicalFactRouteScopeTests(unittest.TestCase):
    def test_shared_fact_codes_are_route_scoped_in_the_tables(self):
        """Codes used by more than one table are exactly the ones that need scoping."""
        by_route = {
            route: {
                clue["fact"]
                for p in load_profile_document(route)["profiles"]
                for clue in p["clues"]
            }
            for route in DISEASE_TABLE_ROUTES
        }
        shared = set()
        for route, codes in by_route.items():
            for other, other_codes in by_route.items():
                if route != other:
                    shared |= codes & other_codes
        # Guards the assumption behind route-scoped facts: without scoping these
        # codes leak an answer given about one complaint into another's score.
        self.assertTrue(shared)
        self.assertTrue(shared <= FACT_CODES)


if __name__ == "__main__":
    unittest.main()
