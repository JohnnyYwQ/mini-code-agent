"""Application composition shared by Web and CLI entry points."""

import atexit
import logging
import os
from functools import lru_cache
from pathlib import Path

from anthropic import Anthropic
from core.agent_runtime import AgentRuntime, AgentRuntimeConfig
from core.memory.composition import MemoryCompositionConfig, build_memory
from core.memory.config import AnthropicLLMConfig
from core.memory.memory import Memory
from dotenv import load_dotenv

from chat.application import ConversationRuntimeContext

logger = logging.getLogger(__name__)

load_dotenv(override=False)


def _agent_config() -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        model=os.getenv("MODEL_ID", ""),
        api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        base_url=os.getenv("ANTHROPIC_BASE_URL") or None,
    )


def _qdrant_location() -> str:
    location = os.getenv(
        "MEMORY_QDRANT_LOCATION",
        str(Path.home() / ".mini-code-agent" / "qdrant"),
    )
    if location == ":memory:" or "://" in location:
        return location
    return str(Path(location).expanduser().resolve())


@lru_cache(maxsize=1)
def _production_memory() -> Memory:
    agent_config = _agent_config()
    return build_memory(
        config=MemoryCompositionConfig(
            llm=AnthropicLLMConfig(
                api_key=agent_config.api_key,
                model=agent_config.model,
                max_tokens=int(os.getenv("MEMORY_MAX_TOKENS", "1200")),
                base_url=agent_config.base_url,
            ),
            qdrant_location=_qdrant_location(),
            collection_name=os.getenv(
                "MEMORY_QDRANT_COLLECTION",
                "mini_code_agent_memories",
            ),
        )
    )


def close_production_memory() -> None:
    """Close the cached production Memory without initializing a new one."""
    if _production_memory.cache_info().currsize == 0:
        return

    memory = _production_memory()
    try:
        memory.close()
    except Exception:
        logger.warning("Memory shutdown failed", exc_info=True)
    finally:
        _production_memory.cache_clear()


atexit.register(close_production_memory)


def _build_runner(
    context: ConversationRuntimeContext,
    *,
    allow_interactive_confirmation: bool,
) -> AgentRuntime:
    config = _agent_config()
    try:
        memory = _production_memory()
    except Exception:
        logger.warning(
            "Memory initialization failed; continuing without Memory",
            exc_info=True,
        )
        memory = None

    return AgentRuntime(
        workspace_path=context.workspace_path,
        config=config,
        message_client=Anthropic(
            api_key=config.api_key,
            base_url=config.base_url,
        ),
        memory=memory,
        memory_context=context.memory_context if memory is not None else None,
        confirm_destructive=(
            None if allow_interactive_confirmation else lambda block: False
        ),
    )


def build_web_runner(context: ConversationRuntimeContext) -> AgentRuntime:
    return _build_runner(context, allow_interactive_confirmation=False)


def build_cli_runner(context: ConversationRuntimeContext) -> AgentRuntime:
    return _build_runner(context, allow_interactive_confirmation=True)
