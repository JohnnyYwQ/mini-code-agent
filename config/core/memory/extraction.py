import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict

from core.memory.llm import LLM, LLMError, LLMMessage
from core.memory.prompts import (
    DEFAULT_MEMORY_EXTRACTION_SYSTEM_PROMPT,
    build_memory_extraction_user_prompt,
)


class MemoryExtractionError(Exception):
    """Raised when an LLM response cannot produce extracted Memories."""


def _response_preview(response: str, *, limit: int = 500) -> str:
    preview = response[:limit]
    if len(response) > limit:
        preview += "...<truncated>"
    return repr(preview)


class MemoryMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class ExtractedMemory:
    text: str
    target: Literal["user", "space"]

    def __post_init__(self) -> None:
        if self.target not in ("user", "space"):
            raise ValueError("target must be 'user' or 'space'")

        if not isinstance(self.text, str):
            raise TypeError("text must be a string")

        text = self.text.strip()
        if not text:
            raise ValueError("text must not be empty")

        object.__setattr__(self, "text", text)


@dataclass(frozen=True, slots=True)
class ExistingMemory:
    reference: str
    text: str
    scope: Literal["user", "space"]


class MemoryExtractor(Protocol):
    def extract(
        self,
        *,
        messages: Sequence[MemoryMessage],
        existing_memories: Sequence[ExistingMemory],
        prompt: str | None = None,
    ) -> list[ExtractedMemory]: ...


class LLMMemoryExtractor(MemoryExtractor):
    def __init__(self, *, llm: LLM) -> None:
        self.llm = llm

    def extract(
        self,
        *,
        messages: Sequence[MemoryMessage],
        existing_memories: Sequence[ExistingMemory],
        prompt: str | None = None,
    ) -> list[ExtractedMemory]:
        user_prompt = build_memory_extraction_user_prompt(
            existing_memories=existing_memories,
            messages=messages,
            custom_instructions=prompt,
        )
        llm_messages: list[LLMMessage] = [
            {
                "role": "system",
                "content": DEFAULT_MEMORY_EXTRACTION_SYSTEM_PROMPT,
            },
            {"role": "user", "content": user_prompt},
        ]
        try:
            response = self.llm.generate_response(messages=llm_messages)
        except LLMError as error:
            raise MemoryExtractionError("LLM failed to extract Memories") from error

        try:
            response_data = json.loads(response)
            if not isinstance(response_data, dict):
                raise TypeError("response must be an object")

            raw_memories = response_data["memory"]
            if not isinstance(raw_memories, list):
                raise TypeError("memory must be a list")

            extracted_memories = []
            for raw_memory in raw_memories:
                if not isinstance(raw_memory, dict):
                    raise TypeError("each memory must be an object")
                extracted_memories.append(
                    ExtractedMemory(
                        text=raw_memory["text"],
                        target=raw_memory["target"],
                    )
                )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise MemoryExtractionError(
                "LLM returned an invalid memory extraction response; "
                f"response preview={_response_preview(response)}"
            ) from error

        return extracted_memories
