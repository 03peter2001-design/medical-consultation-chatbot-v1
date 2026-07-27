import unittest

from questionnaire_ui import build_question_input


class QuestionnaireUiTests(unittest.TestCase):
    def test_multiselect_question_becomes_choices_with_other(self):
        question = (
            "請問肚子痛的性質為何？可以複選：（可複選，以逗號分隔）\n"
            "選項：鈍痛、刺痛、陣痛、持續痛、其他"
        )
        spec = build_question_input(question, step=6, ctype="abdomen")
        self.assertTrue(spec["multiple"])
        self.assertEqual(
            spec["options"], ["鈍痛", "刺痛", "陣痛", "持續痛"]
        )
        self.assertTrue(spec["allow_other"])
        self.assertNotIn("選項：", spec["prompt"])

    def test_single_choice_parenthetical_options(self):
        spec = build_question_input(
            "胸痛是突然發作，還是逐漸發作的呢？（突然發作 / 逐漸發作）",
            step=6,
            ctype="chest",
        )
        self.assertFalse(spec["multiple"])
        self.assertEqual(spec["options"], ["突然發作", "逐漸發作"])

    def test_chest_location_uses_manual_choices(self):
        spec = build_question_input(
            "胸痛的位置在哪裡？左邊、右邊、正中間，還是兩側都有呢？",
            step=7,
            ctype="chest",
        )
        self.assertEqual(
            spec["options"], ["左邊", "右邊", "正中間", "兩側都有"]
        )

    def test_none_option_is_exclusive(self):
        spec = build_question_input(
            "請選擇：（可複選，以逗號分隔）\n選項：發燒、噁心、以上皆無",
            step=8,
            ctype="abdomen",
        )
        self.assertEqual(spec["exclusive_options"], ["以上皆無"])

    def test_free_text_question_has_no_choice_spec(self):
        self.assertIsNone(
            build_question_input(
                "請問您的年齡是？",
                step=1,
                ctype="chest",
            )
        )


if __name__ == "__main__":
    unittest.main()
