import unittest

from app.services.clinical_summary import build_summary


class ClinicalSummaryTests(unittest.TestCase):
    def test_multi_symptom_summary_keeps_each_pipeline_answers(self):
        summary = build_summary(
            {
                "type": "headache",
                "types": ["headache", "abdomen"],
                "reason": "我頭痛且肚子痛",
                "onset": "1天前",
                "location": "前額",
                "abdomen__onset": "3小時前",
                "abdomen__location": "右下腹",
            },
            include_identity=False,
        )

        self.assertIn("頭痛問卷", summary)
        self.assertIn("腹痛問卷", summary)
        self.assertIn("發作時間：1天前", summary)
        self.assertIn("發作時間：3小時前", summary)
        self.assertIn("疼痛位置：前額", summary)
        self.assertIn("疼痛位置：右下腹", summary)

    def test_new_route_summary_uses_its_question_prompts(self):
        summary = build_summary(
            {
                "type": "fever",
                "types": ["fever"],
                "reason": "我發燒",
                "fever_onset": "2天前",
            },
            include_identity=False,
        )

        self.assertIn("發燒問卷", summary)
        self.assertIn("2天前", summary)
        self.assertNotIn("胸痛問卷", summary)

    def test_unmatched_route_summary_does_not_fall_back_to_chest(self):
        summary = build_summary(
            {"type": "other", "reason": "其他不適"},
            include_identity=False,
        )

        self.assertIn("就診原因：其他不適", summary)
        self.assertNotIn("胸痛問卷", summary)


if __name__ == "__main__":
    unittest.main()
