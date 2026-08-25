import unittest
from types import SimpleNamespace

from infrastructure.llm import (
    LLMClient,
    gemini_generation_limits,
    resolve_provider,
)


class ResolveProviderTests(unittest.TestCase):
    def test_keeps_groq_as_default_when_both_keys_exist(self):
        provider = resolve_provider({"GROQ_API_KEY": "groq-key", "GEMINI_API_KEY": "gemini-key"})
        self.assertEqual(provider, "groq")

    def test_uses_gemini_when_it_is_the_only_configured_provider(self):
        provider = resolve_provider({"GEMINI_API_KEY": "gemini-key"})
        self.assertEqual(provider, "gemini")

    def test_explicit_provider_takes_precedence(self):
        provider = resolve_provider(
            {
                "LLM_PROVIDER": "gemini",
                "GROQ_API_KEY": "groq-key",
                "GEMINI_API_KEY": "gemini-key",
            }
        )
        self.assertEqual(provider, "gemini")

    def test_rejects_unknown_provider(self):
        with self.assertRaisesRegex(RuntimeError, "不支援的 LLM_PROVIDER"):
            resolve_provider({"LLM_PROVIDER": "unknown"})

    def test_requires_at_least_one_key(self):
        with self.assertRaisesRegex(RuntimeError, "缺少模型 API Key"):
            resolve_provider({})


class GeminiGenerationTests(unittest.TestCase):
    def test_pro_reserves_minimum_thinking_budget(self):
        output_limit, thinking_budget = gemini_generation_limits(
            "gemini-2.5-pro",
            1400,
            {},
        )
        self.assertEqual(thinking_budget, 128)
        self.assertEqual(output_limit, 1528)

    def test_flash_disables_thinking_by_default(self):
        output_limit, thinking_budget = gemini_generation_limits(
            "gemini-2.5-flash",
            600,
            {},
        )
        self.assertEqual(thinking_budget, 0)
        self.assertEqual(output_limit, 600)

    def test_empty_max_tokens_response_retries_once(self):
        class FakeModels:
            def __init__(self):
                self.configs = []

            def generate_content(self, **kwargs):
                self.configs.append(kwargs["config"])
                if len(self.configs) == 1:
                    return SimpleNamespace(
                        text=None,
                        candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")],
                    )
                return SimpleNamespace(
                    text="完成內容",
                    candidates=[SimpleNamespace(finish_reason="STOP")],
                )

        fake_models = FakeModels()
        client = LLMClient.__new__(LLMClient)
        client.provider = "gemini"
        client.model = "gemini-2.5-pro"
        client._env = {}
        client._client = SimpleNamespace(models=fake_models)

        text = client.generate_text(
            [{"role": "user", "content": "測試"}],
            temperature=0.2,
            max_tokens=1400,
        )

        self.assertEqual(text, "完成內容")
        self.assertEqual(len(fake_models.configs), 2)
        self.assertEqual(fake_models.configs[0].max_output_tokens, 1528)
        self.assertEqual(fake_models.configs[0].temperature, 0.2)
        self.assertGreater(
            fake_models.configs[1].max_output_tokens,
            fake_models.configs[0].max_output_tokens,
        )

    def test_gemini_35_and_newer_omit_unsupported_temperature(self):
        class FakeModels:
            def __init__(self):
                self.configs = []

            def generate_content(self, **kwargs):
                self.configs.append(kwargs["config"])
                return SimpleNamespace(
                    text="完成內容",
                    candidates=[SimpleNamespace(finish_reason="STOP")],
                )

        for model in ("gemini-3.5-flash-lite", "gemini-3.6-flash"):
            with self.subTest(model=model):
                fake_models = FakeModels()
                client = LLMClient.__new__(LLMClient)
                client.provider = "gemini"
                client.model = model
                client._env = {}
                client._client = SimpleNamespace(models=fake_models)

                client.generate_text(
                    [{"role": "user", "content": "測試"}],
                    temperature=0.2,
                    max_tokens=600,
                )

                self.assertIsNone(fake_models.configs[0].temperature)

    def test_gemini_structured_output_passes_json_schema_to_generate_content(self):
        class FakeModels:
            def __init__(self):
                self.config = None

            def generate_content(self, **kwargs):
                self.config = kwargs["config"]
                return SimpleNamespace(
                    text='{"chief_complaint":"Chest pain"}',
                    candidates=[SimpleNamespace(finish_reason="STOP")],
                )

        fake_models = FakeModels()
        client = LLMClient.__new__(LLMClient)
        client.provider = "gemini"
        client.model = "gemini-3.5-flash-lite"
        client._env = {}
        client._client = SimpleNamespace(models=fake_models)
        schema = {
            "type": "object",
            "properties": {"chief_complaint": {"type": "string"}},
            "required": ["chief_complaint"],
        }

        client.generate_text(
            [{"role": "user", "content": "測試"}],
            temperature=0.2,
            max_tokens=240,
            response_json_schema=schema,
        )

        self.assertEqual(fake_models.config.response_mime_type, "application/json")
        self.assertEqual(fake_models.config.response_json_schema, schema)
        self.assertTrue(fake_models.config.automatic_function_calling.disable)


if __name__ == "__main__":
    unittest.main()
