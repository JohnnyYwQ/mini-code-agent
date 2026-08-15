from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from anthropic import APIConnectionError
from core.memory.config import AnthropicLLMConfig
from core.memory.llm import AnthropicLLM, LLMError
from httpx import Request


class AnthropicLLMConfigTests(TestCase):
    def test_rejects_empty_api_key_when_created(self):
        with self.assertRaises(ValueError):
            AnthropicLLMConfig(
                api_key="",
                model="test-model",
                max_tokens=256,
            )

    def test_rejects_empty_model_when_created(self):
        with self.assertRaises(ValueError):
            AnthropicLLMConfig(
                api_key="test-key",
                model="",
                max_tokens=256,
            )

    def test_requires_positive_integer_max_tokens_when_created(self):
        for invalid_max_tokens in (None, 0, -1, 1.5, "256", True):
            with self.subTest(max_tokens=invalid_max_tokens):
                with self.assertRaises(ValueError):
                    AnthropicLLMConfig(
                        api_key="test-key",
                        model="test-model",
                        max_tokens=invalid_max_tokens,  # type: ignore[arg-type]
                    )


class AnthropicLLMTests(TestCase):
    @patch("core.memory.llm.Anthropic")
    def test_translates_messages_and_returns_text(self, anthropic_class):
        client = anthropic_class.return_value
        client.messages.create.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="plain model response"),
            ],
        )
        llm = AnthropicLLM(
            config=AnthropicLLMConfig(
                api_key="test-key",
                model="test-model",
                max_tokens=256,
            ),
        )

        response = llm.generate_response(
            messages=[
                {"role": "system", "content": "Extract Memories."},
                {"role": "user", "content": "I prefer concise replies."},
            ],
        )

        self.assertEqual(response, "plain model response")
        client.messages.create.assert_called_once_with(
            model="test-model",
            max_tokens=256,
            system="Extract Memories.",
            messages=[
                {"role": "user", "content": "I prefer concise replies."},
            ],
        )

    @patch("core.memory.llm.Anthropic")
    def test_translates_anthropic_failure_to_llm_error(self, anthropic_class):
        client = anthropic_class.return_value
        client.messages.create.side_effect = APIConnectionError(
            request=Request("POST", "https://api.anthropic.com/v1/messages"),
        )
        llm = AnthropicLLM(
            config=AnthropicLLMConfig(
                api_key="test-key",
                model="test-model",
                max_tokens=256,
            ),
        )

        with self.assertRaises(LLMError):
            llm.generate_response(
                messages=[
                    {"role": "user", "content": "Hello"},
                ],
            )
