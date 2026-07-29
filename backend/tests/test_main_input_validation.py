import unittest

from app.services.input_validation import (
    store_question_answer,
    validate_question_answer,
)
from domain.questionnaires import build_questionnaire


def question_for(field: str, route: str = "chest") -> dict:
    return next(question for question in build_questionnaire(route) if question["field"] == field)


class MainInputValidationTests(unittest.TestCase):
    def test_gender_accepts_frontend_option_without_normalizing_it(self):
        question = question_for("gender")
        data = {}

        self.assertIsNone(validate_question_answer(question, "女性"))
        stored, displayed = store_question_answer(
            data,
            question,
            "女性",
        )

        self.assertEqual(stored, "女性")
        self.assertEqual(displayed, "女性")
        self.assertEqual(data["gender"], "女性")

    def test_gender_does_not_guess_free_text_or_soundalikes(self):
        question = question_for("gender")

        for answer in ("w", "女", "女生", "呂"):
            with self.subTest(answer=answer):
                self.assertIsNotNone(validate_question_answer(question, answer))

    def test_duration_derives_fields_only_from_exact_numeric_format(self):
        question = question_for("onset")
        data = {}

        self.assertIsNone(validate_question_answer(question, "30分鐘前"))
        store_question_answer(data, question, "30分鐘前")

        self.assertEqual(data["onset"], "30分鐘前")
        self.assertEqual(data["onset_num"], "30")
        self.assertEqual(data["onset_unit"], "分鐘前")

    def test_duration_free_text_is_preserved_without_interpretation(self):
        question = question_for("onset")

        for answer in ("大約昨晚", "一小時前"):
            with self.subTest(answer=answer):
                data = {}
                self.assertIsNone(validate_question_answer(question, answer))
                store_question_answer(data, question, answer)

                self.assertEqual(data["onset"], answer)
                self.assertNotIn("onset_num", data)
                self.assertNotIn("onset_unit", data)

    def test_secondary_symptom_duration_uses_its_own_fields(self):
        questionnaire = build_questionnaire(["headache", "abdomen"])
        question = next(
            item for item in questionnaire if item["field"] == "abdomen__onset"
        )
        data = {"onset": "1天前"}

        self.assertIsNone(validate_question_answer(question, "3小時前"))
        store_question_answer(data, question, "3小時前")

        self.assertEqual(data["onset"], "1天前")
        self.assertEqual(data["abdomen__onset"], "3小時前")
        self.assertEqual(data["abdomen__onset_num"], "3")
        self.assertEqual(data["abdomen__onset_unit"], "小時前")

    def test_invalid_structured_values_are_rejected(self):
        gender = question_for("gender")
        onset = question_for("onset")

        self.assertIsNotNone(validate_question_answer(gender, "男性、女性"))
        self.assertIsNotNone(validate_question_answer(onset, "0小時前"))
        self.assertIsNotNone(validate_question_answer(gender, "..."))


if __name__ == "__main__":
    unittest.main()
