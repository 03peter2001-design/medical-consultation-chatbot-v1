import json
import unittest
from types import SimpleNamespace

from knowledge.translation import (
    GeminiQueryNormalizer,
    QueryNormalization,
    parse_normalization,
    redact_sensitive_text,
)


def valid_payload():
    return {
        "literal_translation": ("No chest pain, but sudden tearing back pain started today."),
        "positive_findings": [
            "sudden tearing back pain",
        ],
        "negative_findings": ["no chest pain"],
        "uncertain_findings": [],
        "temporality": ["started today"],
        "standardized_terms": ["tearing back pain"],
        "retrieval_query": ("sudden tearing back pain without chest pain"),
    }


class FakeModels:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.text)


class RagTranslationTests(unittest.TestCase):
    def test_redacts_common_direct_identifiers(self):
        text = (
            "姓名：王小明，身分證 A123456789，電話 0912-345-678，"
            "email test@example.com，病歷號：MRN778899，"
            "地址：台北市中正區一號；我叫陳大華，今天胸痛"
        )
        redacted = redact_sensitive_text(text)
        for secret in (
            "王小明",
            "A123456789",
            "0912-345-678",
            "test@example.com",
            "MRN778899",
            "台北市中正區一號",
            "陳大華",
        ):
            self.assertNotIn(secret, redacted)
        self.assertIn("今天胸痛", redacted)

    def test_parse_normalization_preserves_structured_findings(self):
        parsed = parse_normalization(json.dumps(valid_payload()))
        self.assertEqual(parsed.negative_findings, ("no chest pain",))
        self.assertIn(
            "tearing back pain",
            parsed.english_search_text(),
        )

    def test_normalizer_sends_only_redacted_text_and_caches_result(self):
        models = FakeModels(json.dumps(valid_payload()))
        client = SimpleNamespace(models=models)
        normalizer = GeminiQueryNormalizer(
            env={
                "RAG_QUERY_TRANSLATION": "gemini",
                "RAG_QUERY_MODE": "dual",
                "GEMINI_API_KEY": "test-key",
            },
            client=client,
        )
        query = "姓名：王小明，A123456789，0912345678，今天突然背痛"

        first = normalizer.normalize(query)
        second = normalizer.normalize(query)

        self.assertIs(first, second)
        self.assertEqual(len(models.calls), 1)
        sent = models.calls[0]["contents"]
        self.assertNotIn("王小明", sent)
        self.assertNotIn("A123456789", sent)
        self.assertNotIn("0912345678", sent)
        self.assertIn("[REDACTED_", sent)
        config = models.calls[0]["config"]
        self.assertEqual(config.response_mime_type, "application/json")

    def test_non_chinese_query_does_not_call_gemini(self):
        models = FakeModels(json.dumps(valid_payload()))
        normalizer = GeminiQueryNormalizer(
            env={
                "RAG_QUERY_TRANSLATION": "gemini",
                "GEMINI_API_KEY": "test-key",
            },
            client=SimpleNamespace(models=models),
        )
        self.assertIsNone(normalizer.normalize("pleuritic chest pain"))
        self.assertEqual(models.calls, [])

    def test_invalid_gemini_output_falls_back(self):
        models = FakeModels('{"retrieval_query": "chest pain"}')
        normalizer = GeminiQueryNormalizer(
            env={
                "RAG_QUERY_TRANSLATION": "gemini",
                "GEMINI_API_KEY": "test-key",
            },
            client=SimpleNamespace(models=models),
        )
        self.assertIsNone(normalizer.normalize("胸痛"))

    def test_invalid_setting_is_safely_disabled(self):
        normalizer = GeminiQueryNormalizer(
            env={
                "RAG_QUERY_TRANSLATION": "unknown",
                "RAG_QUERY_MODE": "unknown",
            }
        )
        self.assertFalse(normalizer.enabled)
        self.assertEqual(normalizer.query_mode, "dual")

    def test_translation_model_does_not_inherit_chat_model(self):
        normalizer = GeminiQueryNormalizer(
            env={
                "RAG_QUERY_TRANSLATION": "gemini",
                "GEMINI_API_KEY": "test-key",
                "GEMINI_MODEL": "gemini-2.5-pro",
            }
        )
        self.assertEqual(normalizer.model, "gemini-2.5-flash")


class QueryNormalizationValueTests(unittest.TestCase):
    def test_retrieval_value_object(self):
        normalized = QueryNormalization(
            literal_translation="The patient denies dyspnea.",
            positive_findings=(),
            negative_findings=("no dyspnea",),
            uncertain_findings=(),
            temporality=(),
            standardized_terms=("dyspnea",),
            retrieval_query="no dyspnea",
        )
        self.assertIn("The patient denies dyspnea", normalized.english_search_text())


if __name__ == "__main__":
    unittest.main()
