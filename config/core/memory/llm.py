from collections.abc import Sequence
from typing import Literal, Protocol, TypedDict

from anthropic import Anthropic, APIError
from anthropic.types import MessageParam

from core.memory.config import AnthropicLLMConfig


class LLMError(Exception):
    """Raised when an LLM adapter cannot produce a response."""


class LLMMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class LLM(Protocol):
    def generate_response(self, *, messages: Sequence[LLMMessage]) -> str: ...


class AnthropicLLM(LLM):
    def __init__(self, *, config: AnthropicLLMConfig) -> None:
        self.config = config
        self.client = Anthropic(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    def generate_response(self, *, messages: Sequence[LLMMessage]) -> str:
        system = "\n\n".join(
            message["content"] for message in messages if message["role"] == "system"
        )
        anthropic_messages: list[MessageParam] = []
        for message in messages:
            if message["role"] == "system":
                continue
            anthropic_messages.append(
                {"role": message["role"], "content": message["content"]}
            )
        try:
            response = self.client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                system=system,
                messages=anthropic_messages,
            )
        except APIError as error:
            raise LLMError("Anthropic request failed") from error

        parts = []
        for block in response.content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)
