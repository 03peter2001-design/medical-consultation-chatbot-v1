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


class QuestionnaireWiringDebtTests(unittest.TestCase):
    """An option with no fact mapping cannot influence disease scoring.

    The patient still spends a turn on it and the answer still reaches the
    clinician as text, but it cannot move the differential or contribute to the
    question's disease-vote utility. Required and priority policy can still keep
    the *field* in the interview. General history is droppable because its three
    optional fields have neither fact mappings nor required status.
    """

    # Keep the baseline explicit: a total-only ceiling would allow a newly
    # unwired high-risk option to be hidden by wiring an unrelated old one.
    KNOWN_UNWIRED_OPTIONS = {
        "history.smoke": {"有，目前仍在抽", "沒有，從未抽菸", "過去有抽，但已戒菸"},
        "history.chronic": {
            "糖尿病",
            "慢性腎病",
            "高血脂",
            "肝硬化",
            "自體免疫疾病",
            "癌症",
            "以上皆無",
        },
        "history.past_meds": {"抗組織胺", "腎上腺素", "類固醇", "以上皆無"},
        "history.current_meds": {"沒有"},
        "history.allergy": {"沒有"},
        "chest.location": {"兩側都有"},
        "chest.fixed": {"痛點會移動"},
        "chest.quality": {"刺痛", "鈍痛"},
        "chest.relieve": {"休息", "用藥", "按摩疼痛部位"},
        "chest.associated": {"肚子痛"},
        "chest.cardio": {
            "高血壓",
            "心絞痛",
            "心臟衰竭",
            "心肌梗塞",
            "心律不整",
            "主動脈剝離",
            "肺栓塞",
            "肺高壓",
            "心包膜積水",
            "氣喘",
            "肺癌",
            "慢性阻塞型肺病",
            "支氣管擴張",
            "氣胸",
            "中風",
            "以上皆無",
        },
        "chest.surgery": {
            "心臟支架",
            "心臟血管繞道手術",
            "主動脈人工血管置換",
            "主動脈支架",
            "心律調節器",
            "氣胸胸腔鏡手術",
            "腦部手術",
            "水腦引流",
            "頸動脈手術",
            "腦部放射線治療",
            "頸椎手術",
            "未曾手術",
        },
        "abdomen.quality": {"鈍痛", "刺痛"},
        "abdomen.location": {"左上腹"},
        "abdomen.associated": {"呼吸道症狀"},
        "abdomen.abdomen_hx": {"盲腸炎", "紫質症", "糖尿病酮酸中毒"},
        "headache.location": {"前額"},
        "headache.worst_ever": {"不是，跟以前差不多或較輕"},
        "headache.quality": {"針刺般的刺痛"},
        "headache.aggravate": {"彎腰低頭"},
        "headache.relieve": {"休息", "使用止痛藥"},
        "headache.neuro": {
            "中風",
            "腦出血",
            "腦膜炎或腦炎",
            "腦部腫瘤",
            "癲癇",
            "顳動脈炎",
        },
        "headache.surgery": {
            "腦部手術",
            "腦動脈瘤夾閉或栓塞手術",
            "水腦引流",
            "頸動脈手術",
            "腦部放射線治療",
            "頸椎手術",
            "未曾手術",
        },
    }

    def _unwired(self):
        unwired = {}
        for category in sorted({"chief", "history", *DISEASE_TABLE_ROUTES}):
            for item in load_questionnaire_category(category):
                mapped = item.get("semantic_options") or {}
                missing = [o for o in (item.get("options") or []) if o not in mapped]
                if missing:
                    unwired[f"{category}.{item['field']}"] = set(missing)
        return unwired

    def test_unwired_option_debt_does_not_spread(self):
        actual = self._unwired()
        unexpected = {
            field: options - self.KNOWN_UNWIRED_OPTIONS.get(field, set())
            for field, options in actual.items()
            if options - self.KNOWN_UNWIRED_OPTIONS.get(field, set())
        }
        self.assertFalse(
            unexpected,
            f"新增了沒有 fact 對應的選項，將無法影響疾病評分：{unexpected}",
        )

    def test_every_cardiac_history_option_is_currently_unwired(self):
        """Pins the largest single gap: prior MI/stent cannot reach the funnel."""
        self.assertEqual(len(self._unwired().get("chest.cardio", [])), 16)


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
