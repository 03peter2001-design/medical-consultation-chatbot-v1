import json
import unittest
from datetime import date

from domain.questionnaires import (
    CHIEF_QUESTIONNAIRE,
    DISEASE_QUESTIONNAIRES,
    QUESTIONNAIRE_DATA_DIR,
    build_questionnaire,
    load_questionnaire_category,
    next_question_index,
    parse_birth_date,
    parse_onset_answer,
)


class QuestionnaireDefinitionTests(unittest.TestCase):
    def test_questionnaire_content_is_split_into_category_json_files(self):
        expected = {
            "chief",
            "basic",
            "history",
            "chest",
            "headache",
            "abdomen",
        }
        actual = {path.stem for path in QUESTIONNAIRE_DATA_DIR.glob("*.json")}
        self.assertEqual(actual, expected)
        for category in expected:
            document = json.loads(
                (QUESTIONNAIRE_DATA_DIR / f"{category}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(document["id"], category)
            self.assertTrue(document["questions"])

    def test_category_loader_is_cached_and_rejects_unknown_category(self):
        first = load_questionnaire_category("chest")
        second = load_questionnaire_category("chest")
        self.assertIs(first, second)
        with self.assertRaisesRegex(ValueError, "不支援"):
            load_questionnaire_category("unknown")

    def test_flow_is_chief_then_basic_history_and_disease(self):
        questionnaire = build_questionnaire("abdomen")
        sections = [item["section"] for item in questionnaire]
        first_basic = sections.index("basic")
        first_history = sections.index("history")
        first_disease = sections.index("disease")

        self.assertEqual(questionnaire[0]["field"], "reason")
        self.assertLess(first_basic, first_history)
        self.assertLess(first_history, first_disease)

    def test_each_supported_route_has_a_disease_questionnaire(self):
        self.assertEqual(
            set(DISEASE_QUESTIONNAIRES),
            {"chest", "headache", "abdomen"},
        )
        for route in DISEASE_QUESTIONNAIRES:
            questionnaire = build_questionnaire(route)
            self.assertTrue(any(item["section"] == "disease" for item in questionnaire))
            onset = next(item for item in questionnaire if item["field"] == "onset")
            self.assertEqual(onset["kind"], "duration")
            self.assertIn("1週前", onset["quick_options"])
            self.assertIn("個月前", onset["units"])

    def test_multiple_symptom_routes_share_demographics_but_keep_answers_separate(self):
        questionnaire = build_questionnaire(["headache", "abdomen"])
        fields = [item["field"] for item in questionnaire]
        disease = [item for item in questionnaire if item["section"] == "disease"]

        self.assertEqual(fields.count("name"), 1)
        self.assertEqual(len(fields), len(set(fields)))
        self.assertEqual(
            [item["route"] for item in disease if item["base_field"] == "onset"],
            ["headache", "abdomen"],
        )
        self.assertIn("onset", fields)
        self.assertIn("abdomen__onset", fields)
        self.assertIn("abdomen__location", fields)

    def test_selectable_basic_fields_are_structured(self):
        questionnaire = build_questionnaire("chest")
        by_field = {item["field"]: item for item in questionnaire}
        self.assertEqual(by_field["gender"]["kind"], "choice")
        self.assertEqual(by_field["birth_date"]["kind"], "date")
        self.assertEqual(by_field["blood_type"]["kind"], "choice")

    def test_optional_chronic_detail_is_skipped(self):
        questionnaire = build_questionnaire("headache")
        chronic_index = next(
            index for index, item in enumerate(questionnaire) if item["field"] == "chronic"
        )
        next_index = next_question_index(
            questionnaire,
            chronic_index,
            {"chronic": "以上皆無"},
        )
        self.assertEqual(questionnaire[next_index]["field"], "past_meds")

    def test_fhir_prefilled_basic_fields_are_skipped(self):
        questionnaire = build_questionnaire("abdomen")
        next_index = next_question_index(
            questionnaire,
            0,
            {},
            skip_fields={
                "name",
                "gender",
                "birth_date",
                "blood_type",
            },
        )
        self.assertEqual(questionnaire[next_index]["field"], "smoke")

    def test_headache_neuro_and_surgery_prefill_skips_both_questions(self):
        questionnaire = build_questionnaire("headache")
        risk_index = next(
            index for index, item in enumerate(questionnaire) if item["field"] == "risk_flags"
        )
        self.assertIsNone(
            next_question_index(
                questionnaire,
                risk_index,
                {},
                skip_fields={"neuro", "surgery"},
            )
        )

    def test_initial_questionnaire_only_asks_for_chief_complaint(self):
        self.assertEqual(len(CHIEF_QUESTIONNAIRE), 1)
        self.assertEqual(CHIEF_QUESTIONNAIRE[0]["kind"], "text")


class QuestionnaireParserTests(unittest.TestCase):
    def test_birth_date_derives_age(self):
        self.assertEqual(
            parse_birth_date("1990-08-01", today=date(2026, 7, 27)),
            ("1990-08-01", 35),
        )

    def test_future_birth_date_is_rejected(self):
        self.assertIsNone(parse_birth_date("2027-01-01", today=date(2026, 7, 27)))

    def test_onset_preserves_months(self):
        self.assertEqual(
            parse_onset_answer("一個月以前"),
            ("1", "個月前"),
        )
        self.assertEqual(parse_onset_answer("1個月以前"), ("1", "個月前"))

    def test_onset_does_not_default_to_hours(self):
        self.assertIsNone(parse_onset_answer("有一陣子了"))


if __name__ == "__main__":
    unittest.main()
