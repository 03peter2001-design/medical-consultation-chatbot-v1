import json
import unittest

from app.services import differential_coding


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def generate_text(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return json.dumps(self.response, ensure_ascii=False)


class DifferentialCodingTests(unittest.TestCase):
    def setUp(self):
        differential_coding._coding_cache.clear()

    def test_adds_snomed_suggestion_without_sending_patient_data(self):
        llm = FakeLLM(
            [
                {
                    "condition": "顱內出血",
                    "coding": {
                        "system": "http://snomed.info/sct",
                        "code": "1386000",
                        "display": "Intracranial hemorrhage",
                    },
                }
            ]
        )

        result = differential_coding.suggest_missing_differential_codings(
            [
                {
                    "condition": "顱內出血",
                    "supporting_evidence": ["病人姓名與病史不應送出"],
                }
            ],
            llm,
        )

        self.assertEqual(result[0]["coding"]["code"], "1386000")
        self.assertEqual(result[0]["coding"]["source"], "ai-suggested")
        prompt = llm.calls[0]["messages"][1]["content"]
        self.assertIn("顱內出血", prompt)
        self.assertNotIn("病人姓名", prompt)

    def test_keeps_existing_coding_without_calling_model(self):
        llm = FakeLLM([])
        coding = {
            "system": "http://snomed.info/sct",
            "code": "29857009",
            "display": "Chest pain",
            "source": "ai-suggested",
        }

        result = differential_coding.suggest_missing_differential_codings(
            [{"condition": "胸痛", "coding": coding}],
            llm,
        )

        self.assertEqual(result[0]["coding"], coding)
        self.assertEqual(llm.calls, [])

    def test_discards_malformed_model_coding(self):
        llm = FakeLLM(
            [
                {
                    "condition": "未知疾病",
                    "coding": {
                        "system": "http://example.com",
                        "code": "not-a-code",
                        "display": "Unknown",
                    },
                }
            ]
        )

        result = differential_coding.suggest_missing_differential_codings(
            [{"condition": "未知疾病"}],
            llm,
        )

        self.assertIsNone(result[0]["coding"])


if __name__ == "__main__":
    unittest.main()
