from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.memory.extraction import ExistingMemory, MemoryMessage


DEFAULT_MEMORY_EXTRACTION_SYSTEM_PROMPT = """
You are a Memory Extractor. Extract stable, reusable facts from new messages.
Compare them with existing memories and do not repeat semantically equivalent facts.
Prefer newer explicit statements over older ones. Ignore facts that later messages
supersede or contradict.
For every extracted memory, choose exactly one target:
- Use {"target": "user"} only for facts that should apply across all Memory Spaces owned by the user.
- Use {"target": "space"} for facts limited to the current Memory Space, and whenever the scope is uncertain.
Return only a JSON object shaped like {"memory": [{"text": "...", "target": "user"}]} or
{"memory": [{"text": "...", "target": "space"}]}.
Return {"memory": []} when there is nothing new to remember.
""".strip()


def build_memory_extraction_user_prompt(
    *,
    existing_memories: Sequence[ExistingMemory],
    messages: Sequence[MemoryMessage],
    custom_instructions: str | None,
) -> str:
    sections = [
        "## Existing Memories\n"
        + json.dumps(
            [
                {
                    "reference": memory.reference,
                    "text": memory.text,
                    "scope": memory.scope,
                }
                for memory in existing_memories
            ],
            ensure_ascii=False,
        ),
        "## New Messages\n"
        + json.dumps([dict(message) for message in messages], ensure_ascii=False),
    ]

    if custom_instructions:
        sections.append(f"## Custom Instructions\n{custom_instructions}")

    return "\n\n".join(sections)
