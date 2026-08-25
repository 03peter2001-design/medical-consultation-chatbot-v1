import json
import unittest

from app.prompts.questionnaire_summary import (
    EMR_TASKS,
    SUMMARY_TASKS,
    build_summary_prompt_request,
    build_summary_prompt_requests,
    summary_response_schema,
)
from app.services.gemini_questionnaire_summary import (
    parse_summary_section,
    parse_summary_sections,
    render_emr,
)


def _valid_sections() -> dict[str, str]:
    values = {
        "chief_complaint": "chest pain for 30 minutes",
        "present_illness": "The pain began during exertion.",
        "past_history": "Not provided",
        "drug_history": ("Past medications: antihistamines. Current medications: none reported."),
        "drug_allergy_history": "Not provided",
        "personal_history": "Not provided",
        "family_history": "Not provided",
        "differential_diagnoses": ["Acute coronary syndrome"],
        "must_not_miss": ["Aortic dissection"],
        "physical_examination": ["Bilateral blood pressure measurement"],
        "laboratory": ["High-sensitivity cardiac troponin"],
        "imaging": ["Chest radiograph"],
    }
    return {task: json.dumps({task: values[task]}, ensure_ascii=False) for task in SUMMARY_TASKS}


class GeminiQuestionnaireSummaryTests(unittest.TestCase):
    def test_api_response_schema_matches_each_atomic_task_type(self):
        for task in SUMMARY_TASKS:
            schema = summary_response_schema(task)

            self.assertEqual(schema["required"], [task])
            self.assertEqual(set(schema["properties"]), {task})
            self.assertIs(schema["additionalProperties"], False)
            expected_type = "string" if task in EMR_TASKS else "array"
            self.assertEqual(schema["properties"][task]["type"], expected_type)
            if task not in EMR_TASKS:
                self.assertEqual(schema["properties"][task]["items"], {"type": "string"})

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
        for task in EMR_TASKS:
            self.assertNotIn("retrieved_evidence", payloads[task])
        self.assertEqual(
            payloads["chief_complaint"]["question"],
            "What is the chief complaint?",
        )
        self.assertNotIn("age", payloads["chief_complaint"]["patient_context"]["prefilled_data"])
        self.assertNotIn("patient_demographics", payloads["chief_complaint"]["patient_context"])
        self.assertIn(
            "Do not include or calculate age or sex", payloads["chief_complaint"]["rules"]
        )
        self.assertEqual(payloads["present_illness"]["question"], "What is the present illness?")
        self.assertEqual(payloads["past_history"]["question"], "What is the past history?")
        self.assertEqual(payloads["drug_history"]["question"], "What is the drug history?")
        self.assertIn("past medication treatments", payloads["drug_history"]["rules"])
        self.assertIn("current medications", payloads["drug_history"]["rules"])
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
        parsed = parse_summary_sections(
            _valid_sections(),
            patient_age="58",
            patient_sex="男性",
        )

        self.assertEqual(
            parsed.emr["cc"],
            "A 58-year-old male patient presents with chest pain for 30 minutes.",
        )
        self.assertEqual(parsed.emr["personal"], "Not provided")
        self.assertEqual(parsed.laboratory[0], "High-sensitivity cardiac troponin")

        missing = _valid_sections()
        missing.pop("laboratory")
        with self.assertRaisesRegex(ValueError, "missing or extra"):
            parse_summary_sections(missing)

        extra_key = _valid_sections()
        extra_key["chief_complaint"] = json.dumps(
            {
                "chief_complaint": "Chest pain.",
                "imaging": [],
            },
            ensure_ascii=False,
        )
        with self.assertRaisesRegex(ValueError, "chief_complaint response has an invalid shape"):
            parse_summary_sections(extra_key)

        invalid_item = _valid_sections()
        invalid_item["laboratory"] = json.dumps(
            {"laboratory": [{"item": "Troponin", "rationale": "legacy shape"}]}
        )
        with self.assertRaisesRegex(ValueError, "items must be text"):
            parse_summary_sections(invalid_item)

    def test_renderer_preserves_requested_medical_history_paragraph_order(self):
        rendered = render_emr(
            parse_summary_sections(
                _valid_sections(),
                patient_age="58",
                patient_sex="男性",
            ),
            model="gemini-test",
        )

        headings = [
            "Chief Complaint:",
            "Present Illness:",
            "Past History:",
            "Drug History:",
            "Allergy History:",
            "Personal History:",
            "Family History:",
        ]
        positions = [rendered.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("fixed-questionnaire-complete-drug-history-v9", rendered)

    def test_missing_demographics_are_explicit_in_one_sentence_chief_complaint(self):
        parsed = parse_summary_sections(_valid_sections())

        self.assertEqual(
            parsed.emr["cc"],
            "A patient (age: Not provided; sex: Not provided) presents with chest pain for 30 minutes.",
        )


if __name__ == "__main__":
    unittest.main()
