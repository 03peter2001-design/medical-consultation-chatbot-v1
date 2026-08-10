import ast
import json
import tempfile
import unittest
from pathlib import Path

from app.services.input_validation import validate_question_answer
from app.services.patient_interview import section_transition_reply
from domain.patient_messages import (
    EXPECTED_MESSAGE_FIELDS,
    PATIENT_MESSAGES_PATH,
    load_patient_messages,
    patient_message,
)


class PatientMessageCatalogTests(unittest.TestCase):
    def test_catalog_is_complete_and_templates_render(self):
        messages = load_patient_messages()

        self.assertEqual(set(messages), set(EXPECTED_MESSAGE_FIELDS))
        self.assertEqual(
            patient_message("navigation.previous_question", prompt="下一題？"),
            "已回到上一題，您可以重新作答。\n\n下一題？",
        )
        self.assertIn(
            "編號為：123",
            patient_message("completion.routine", queue_number="123"),
        )

    def test_catalog_rejects_missing_messages_and_placeholder_drift(self):
        document = json.loads(PATIENT_MESSAGES_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "patient_messages.json"

            missing = json.loads(json.dumps(document, ensure_ascii=False))
            missing["messages"].pop("interview.amie_welcome")
            path.write_text(json.dumps(missing, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "文案不同步"):
                load_patient_messages(path)

            drifted = json.loads(json.dumps(document, ensure_ascii=False))
            drifted["messages"]["interview.amie_welcome"] += "{unknown}"
            path.write_text(json.dumps(drifted, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "placeholders 不正確"):
                load_patient_messages(path)

    def test_render_rejects_missing_or_extra_dynamic_values(self):
        with self.assertRaisesRegex(ValueError, "參數不正確"):
            patient_message("completion.routine")
        with self.assertRaisesRegex(ValueError, "參數不正確"):
            patient_message("validation.empty", unused="value")

    def test_section_transitions_and_validation_use_the_catalog(self):
        self.assertEqual(
            section_transition_reply(
                "chief",
                {"section": "basic", "prompt": "請問姓名？"},
                "chest",
            ),
            patient_message("section.basic", prompt="請問姓名？"),
        )
        self.assertEqual(
            validate_question_answer({"kind": "text"}, ""),
            patient_message("validation.empty"),
        )

    def test_patient_reply_arguments_are_not_inline_string_literals(self):
        source_path = Path(__file__).resolve().parents[1] / "app" / "routes" / "patient.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        inline_replies = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "reply" and isinstance(
                    keyword.value,
                    (ast.Constant, ast.JoinedStr),
                ):
                    inline_replies.append(keyword.value.lineno)

        self.assertEqual(inline_replies, [])


if __name__ == "__main__":
    unittest.main()
