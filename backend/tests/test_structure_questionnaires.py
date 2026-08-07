import unittest

from scripts.structure_questionnaires import (
    SourceQuestionnaire,
    _option_is_source_supported,
    parse_source,
    validate_payload,
)


class StructureQuestionnairesTests(unittest.TestCase):
    def test_parse_source_preserves_numbered_lines_and_common_sections(self):
        source = """\ufeff患者基本資料
1. 詢問性別？

詢問就診原因？（判斷類別）
1. 胸痛
胸痛何時開始？
突然
逐漸
2. 發燒
何時發燒？ *

詢問過去病史
1. 是否抽菸？
"""

        questionnaires, basic, history = parse_source(source)

        self.assertEqual([item.order for item in questionnaires], [1, 2])
        self.assertEqual(questionnaires[0].label, "胸痛")
        self.assertEqual(questionnaires[0].lines, ("胸痛何時開始？", "突然", "逐漸"))
        self.assertIn("1. 詢問性別？", basic)
        self.assertIn("1. 是否抽菸？", history)

    def test_validate_payload_requires_lossless_source_trace(self):
        source = SourceQuestionnaire(
            order=1,
            label="胸痛",
            lines=("胸痛何時開始？", "突然", "逐漸"),
        )
        payload = {
            "id": "chest_pain",
            "label": "胸痛",
            "questions": [
                {
                    "field": "onset",
                    "prompt": "胸痛何時開始？",
                    "kind": "choice",
                    "options": ["突然", "逐漸"],
                    "multiple": False,
                    "allow_other": True,
                    "exclusive_options": [],
                    "quick_options": [],
                    "units": [],
                    "placeholder": "",
                    "condition": None,
                    "option_conditions": {},
                    "semantic_options": {},
                    "source_lines": ["胸痛何時開始？", "突然", "逐漸"],
                }
            ],
            "required_fields": ["onset"],
            "priority_fields": ["onset"],
            "review_notes": [],
        }

        validated = validate_payload(payload, source)

        self.assertEqual(validated["questions"][0]["field"], "onset")

    def test_validate_payload_rejects_dropped_source_line(self):
        source = SourceQuestionnaire(order=1, label="胸痛", lines=("問題？", "選項"))
        payload = {
            "id": "chest_pain",
            "label": "胸痛",
            "questions": [
                {
                    "field": "symptom",
                    "prompt": "問題？",
                    "kind": "text",
                    "options": [],
                    "multiple": False,
                    "allow_other": True,
                    "exclusive_options": [],
                    "quick_options": [],
                    "units": [],
                    "placeholder": "",
                    "condition": None,
                    "option_conditions": {},
                    "semantic_options": {},
                    "source_lines": ["問題？"],
                }
            ],
            "required_fields": [],
            "priority_fields": [],
            "review_notes": [],
        }

        with self.assertRaisesRegex(ValueError, "source_lines 數量不符"):
            validate_payload(payload, source)

    def test_validate_payload_rejects_invented_choice(self):
        source = SourceQuestionnaire(order=1, label="胸痛", lines=("是否正在擴散？",))
        payload = {
            "id": "chest_pain",
            "label": "胸痛",
            "questions": [
                {
                    "field": "progression",
                    "prompt": "是否正在擴散？",
                    "kind": "choice",
                    "options": ["是", "否", "已經痊癒"],
                    "multiple": False,
                    "allow_other": True,
                    "exclusive_options": [],
                    "quick_options": [],
                    "units": [],
                    "placeholder": "",
                    "condition": None,
                    "option_conditions": {},
                    "semantic_options": {},
                    "source_lines": ["是否正在擴散？"],
                }
            ],
            "required_fields": [],
            "priority_fields": [],
            "review_notes": [],
        }

        with self.assertRaisesRegex(ValueError, "無逐字來源支持"):
            validate_payload(payload, source)

    def test_validate_payload_allows_narrow_source_typo_correction(self):
        source = SourceQuestionnaire(
            order=1,
            label="背痛",
            lines=("是否有其他症狀", "小便會疼痛或是休血尿"),
        )
        payload = {
            "id": "back_pain",
            "label": "背痛",
            "questions": [
                {
                    "field": "associated",
                    "prompt": "是否有其他症狀",
                    "kind": "choice",
                    "options": ["小便會疼痛或是血尿"],
                    "multiple": True,
                    "allow_other": True,
                    "exclusive_options": [],
                    "quick_options": [],
                    "units": [],
                    "placeholder": "",
                    "condition": None,
                    "option_conditions": {},
                    "semantic_options": {},
                    "source_lines": ["是否有其他症狀", "小便會疼痛或是休血尿"],
                }
            ],
            "required_fields": [],
            "priority_fields": [],
            "review_notes": [],
        }

        self.assertEqual(validate_payload(payload, source)["id"], "back_pain")

    def test_typo_correction_cannot_flip_negation(self):
        self.assertFalse(
            _option_is_source_supported(
                "最近沒有發生過低血糖或高血糖事件",
                ["最近有發生過低血糖或高血糖事件？"],
                "最近有發生過低血糖或高血糖事件？",
            )
        )


if __name__ == "__main__":
    unittest.main()
