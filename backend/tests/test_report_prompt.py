import unittest

from app.prompts.doctor import build_structured_note_prompt
from app.prompts.report import build_report_prompt


class ReportPromptTests(unittest.TestCase):
    def test_structured_emr_prompt_requests_the_two_sentence_card_template(self):
        prompt = build_structured_note_prompt(
            "走路時胸悶",
            None,
            "鑑別資料",
            "檢驗資料",
            "影像資料",
        )

        self.assertIn("{年齡}歲{男性／女性／其他}", prompt)
        self.assertIn("持續時間：{多久}", prompt)
        self.assertIn("用恰好兩句", prompt)
        self.assertIn("本段只能有上述兩行", prompt)
        self.assertNotIn("CC（主訴）", prompt)

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
