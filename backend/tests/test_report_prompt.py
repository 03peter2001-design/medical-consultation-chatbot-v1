import unittest

from app.prompts.report import build_report_prompt


class ReportPromptTests(unittest.TestCase):
    def test_prompt_requests_one_physician_facing_paragraph_near_300_total_chars(self):
        prompt = build_report_prompt(
            {
                "type": "chest",
                "gender": "男",
                "age": "58",
                "reason": "走路時胸悶",
            }
        )

        self.assertIn("供醫師快速閱讀", prompt)
        self.assertIn("只輸出一個自然段落", prompt)
        self.assertIn("160至220字", prompt)
        self.assertIn("可能疾病與理由會由系統依固定疾病表", prompt)
        self.assertNotIn("姓名", prompt)


if __name__ == "__main__":
    unittest.main()
