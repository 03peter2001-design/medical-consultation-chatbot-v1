import json
import unittest

from app.prompts.doctor import (
    DOCTOR_SYSTEM_PROMPT,
    STRUCTURED_NOTE_TASKS,
    build_structured_note_prompt,
    build_structured_note_prompts,
    render_structured_note_responses,
)
from app.prompts.report import build_report_prompt


class ReportPromptTests(unittest.TestCase):
    def test_structured_note_builds_one_scoped_prompt_per_question(self):
        prompts = build_structured_note_prompts(
            "走路時胸悶",
            None,
            "鑑別資料",
            "檢驗資料",
            "影像資料",
        )

        self.assertEqual([prompt.task for prompt in prompts], list(STRUCTURED_NOTE_TASKS))
        payloads = {prompt.task: json.loads(prompt.messages[-1]["content"]) for prompt in prompts}
        for task, payload in payloads.items():
            self.assertEqual(set(payload["response_schema"]), {task})
            self.assertEqual(payload["patient_context"]["physician_input"], "走路時胸悶")
            self.assertNotIn("每次只回答", prompts[0].messages[0]["content"])

        self.assertNotIn("retrieved_evidence", payloads["emr"])
        self.assertEqual(payloads["differential_diagnoses"]["retrieved_evidence"], "鑑別資料")
        self.assertEqual(payloads["must_not_miss"]["retrieved_evidence"], "鑑別資料")
        self.assertEqual(payloads["physical_examination"]["retrieved_evidence"], "鑑別資料")
        self.assertEqual(payloads["laboratory"]["retrieved_evidence"], "檢驗資料")
        self.assertEqual(payloads["imaging"]["retrieved_evidence"], "影像資料")
        self.assertNotIn("檢驗資料", prompts[1].messages[-1]["content"])
        self.assertNotIn("影像資料", prompts[1].messages[-1]["content"])

        laboratory = build_structured_note_prompt(
            "laboratory",
            "走路時胸悶",
            None,
            "鑑別資料",
            "檢驗資料",
            "影像資料",
            focus_conditions="Aortic dissection\nPulmonary embolism",
        )
        laboratory_payload = json.loads(laboratory.messages[-1]["content"])
        self.assertEqual(
            laboratory_payload["focus_conditions"],
            "Aortic dissection\nPulmonary embolism",
        )

    def test_general_physician_rag_chat_remains_traditional_chinese(self):
        self.assertIn("請用繁體中文", DOCTOR_SYSTEM_PROMPT)
        self.assertNotIn("請用英文", DOCTOR_SYSTEM_PROMPT)

    def test_structured_note_renderer_requires_every_task_and_preserves_order(self):
        responses = {
            task: json.dumps({task: f"{task}內容"}, ensure_ascii=False)
            for task in STRUCTURED_NOTE_TASKS
        }

        rendered = render_structured_note_responses(responses)

        self.assertLess(rendered.index("【病歷摘要 EMR】"), rendered.index("【影像學決策】"))
        with self.assertRaisesRegex(ValueError, "missing or extra"):
            render_structured_note_responses({"emr": responses["emr"]})
        responses["emr"] = json.dumps({"emr": "【影像學決策】\n不應跨題輸出"}, ensure_ascii=False)
        with self.assertRaisesRegex(ValueError, "section heading"):
            render_structured_note_responses(responses)

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

    def test_new_route_prompt_uses_the_catalog_label(self):
        prompt = build_report_prompt(
            {
                "type": "fever",
                "gender": "女",
                "age": "30",
                "reason": "發燒",
                "fever_onset": "2天前",
            }
        )

        self.assertIn("發燒主訴", prompt)
        self.assertNotIn("胸痛主訴", prompt)


if __name__ == "__main__":
    unittest.main()
