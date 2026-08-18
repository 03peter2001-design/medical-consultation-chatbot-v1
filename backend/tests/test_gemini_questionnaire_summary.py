import json
import unittest

from app.prompts.questionnaire_summary import (
    SUMMARY_TASKS,
    build_summary_prompt_request,
    build_summary_prompt_requests,
)
from app.services.gemini_questionnaire_summary import parse_summary_section, parse_summary_sections


def _valid_sections() -> dict[str, str]:
    values = {
        "emr": {
            "cc": "Chest pain.",
            "pi": "The pain began during exertion.",
            "ph": "Not provided",
            "meds": "Not provided",
            "allergy": "Not provided",
        },
        "differential_diagnoses": ["Acute coronary syndrome"],
        "must_not_miss": ["Aortic dissection"],
        "physical_examination": ["Bilateral blood pressure measurement"],
        "laboratory": ["High-sensitivity cardiac troponin"],
        "imaging": ["Chest radiograph"],
    }
    return {task: json.dumps({task: values[task]}, ensure_ascii=False) for task in SUMMARY_TASKS}


class GeminiQuestionnaireSummaryTests(unittest.TestCase):
    def test_prompt_registry_has_one_schema_and_relevant_evidence_per_task(self):
        requests = build_summary_prompt_requests(
            [{"field": "reason", "question": "哪裡不舒服？", "answer": "胸痛"}],
            prefilled_data={"age": "58", "_private": "omit"},
            knowledge_contexts={
                "diagnosis": "A evidence",
                "laboratory": "B evidence",
                "imaging": "C evidence",
            },
        )

        self.assertEqual([request.task for request in requests], list(SUMMARY_TASKS))
        payloads = {
            request.task: json.loads(request.messages[-1]["content"]) for request in requests
        }
        for task, payload in payloads.items():
            self.assertEqual(set(payload["response_schema"]), {task})
            self.assertNotIn("_private", payload["patient_context"]["prefilled_data"])
        self.assertNotIn("retrieved_evidence", payloads["emr"])
        self.assertEqual(payloads["must_not_miss"]["retrieved_evidence"], "A evidence")
        self.assertEqual(payloads["laboratory"]["retrieved_evidence"], "B evidence")
        self.assertEqual(payloads["imaging"]["retrieved_evidence"], "C evidence")
        self.assertIn("professional English", requests[0].messages[0]["content"])
        for payload in payloads.values():
            self.assertNotIn(
                "rationale",
                json.dumps(payload["response_schema"], ensure_ascii=False),
            )

    def test_later_tasks_receive_validated_must_not_miss_conditions(self):
        raw = json.dumps({"must_not_miss": ["Aortic dissection", "Pulmonary embolism"]})
        focus = parse_summary_section("must_not_miss", raw)
        self.assertIsInstance(focus, list)

        request = build_summary_prompt_request(
            "laboratory",
            [{"field": "reason", "question": "Symptom?", "answer": "Chest pain"}],
            prefilled_data={},
            knowledge_contexts={"laboratory": "B evidence"},
            focus_conditions=focus if isinstance(focus, list) else [],
        )
        payload = json.loads(request.messages[-1]["content"])

        self.assertEqual(
            payload["focus_conditions"],
            ["Aortic dissection", "Pulmonary embolism"],
        )

    def test_parser_aggregates_only_complete_exact_task_responses(self):
        parsed = parse_summary_sections(_valid_sections())

        self.assertEqual(parsed.emr["cc"], "Chest pain.")
        self.assertEqual(parsed.laboratory[0], "High-sensitivity cardiac troponin")

        missing = _valid_sections()
        missing.pop("laboratory")
        with self.assertRaisesRegex(ValueError, "missing or extra"):
            parse_summary_sections(missing)

        extra_key = _valid_sections()
        extra_key["emr"] = json.dumps(
            {"emr": json.loads(extra_key["emr"])["emr"], "imaging": []},
            ensure_ascii=False,
        )
        with self.assertRaisesRegex(ValueError, "emr response has an invalid shape"):
            parse_summary_sections(extra_key)

        invalid_item = _valid_sections()
        invalid_item["laboratory"] = json.dumps(
            {"laboratory": [{"item": "Troponin", "rationale": "legacy shape"}]}
        )
        with self.assertRaisesRegex(ValueError, "items must be text"):
            parse_summary_sections(invalid_item)


if __name__ == "__main__":
    unittest.main()
