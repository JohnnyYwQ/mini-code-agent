from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from core.memory.memory import MemoryContext
from django.contrib.auth import get_user_model  # type: ignore[import-untyped]
from django.db import transaction  # type: ignore[import-untyped]
from django.utils import timezone  # type: ignore[import-untyped]

from chat.models import Conversation, ConversationMessage, MemorySpace

LOCAL_USERNAME = "local"


class ConversationNotFoundError(LookupError):
    """Raised when a Conversation is unavailable to the local User."""


class WorkspaceUnavailableError(RuntimeError):
    """Raised when a Conversation's workspace cannot run a Turn."""


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    id: UUID
    title: str
    workspace_path: Path
    workspace_available: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ConversationRuntimeContext:
    conversation_id: UUID
    workspace_path: Path
    memory_context: MemoryContext


@dataclass(frozen=True, slots=True)
class TurnResult:
    conversation_id: UUID
    title: str
    assistant_text: str


class AgentRunner(Protocol):
    def run(
        self,
        *,
        messages: Sequence[dict[str, object]],
        latest_user_query: str,
    ) -> list[dict[str, object]]: ...


class AgentResponseError(RuntimeError):
    """Raised when a completed agent run has no visible assistant reply."""


def _get_local_conversation(*, conversation_id: UUID) -> Conversation:
    try:
        return Conversation.objects.select_related("memory_space").get(
            id=conversation_id,
            memory_space__owner__username=LOCAL_USERNAME,
        )
    except Conversation.DoesNotExist as exc:
        raise ConversationNotFoundError(
            f"Conversation {conversation_id} was not found."
        ) from exc


def start_conversation(*, workspace_path: Path) -> Conversation:
    local_user, created = get_user_model().objects.get_or_create(
        username=LOCAL_USERNAME
    )
    if created or local_user.has_usable_password():
        local_user.set_unusable_password()
        local_user.save(update_fields=["password"])

    memory_space, _ = MemorySpace.objects.get_or_create(
        owner=local_user,
        workspace_path=str(workspace_path.resolve()),
    )
    return Conversation.objects.create(memory_space=memory_space)


def resolve_memory_context(*, conversation_id: UUID) -> MemoryContext:
    conversation = _get_local_conversation(conversation_id=conversation_id)

    return MemoryContext(
        user_id=str(conversation.memory_space.owner_id),
        space_id=str(conversation.memory_space_id),
    )


def resolve_workspace_path(*, conversation_id: UUID) -> Path:
    conversation = _get_local_conversation(conversation_id=conversation_id)

    return Path(conversation.memory_space.workspace_path)


def require_available_workspace(*, conversation_id: UUID) -> Path:
    workspace_path = resolve_workspace_path(conversation_id=conversation_id)
    if not workspace_path.is_dir():
        raise WorkspaceUnavailableError(f"Workspace {workspace_path} is unavailable.")
    return workspace_path


def append_conversation_message(
    *,
    conversation_id: UUID,
    message: dict[str, object],
) -> None:
    with transaction.atomic():
        conversation = _get_local_conversation(conversation_id=conversation_id)
        ConversationMessage.objects.create(
            conversation=conversation,
            role=message["role"],
            content=message["content"],
        )
        content = message["content"]
        if (
            not conversation.title
            and message["role"] == "user"
            and isinstance(content, str)
        ):
            conversation.title = " ".join(content.split())[:120]
        conversation.updated_at = timezone.now()
        conversation.save(update_fields=["title", "updated_at"])


def append_conversation_messages(
    *,
    conversation_id: UUID,
    messages: list[dict[str, object]],
) -> None:
    with transaction.atomic():
        conversation = _get_local_conversation(conversation_id=conversation_id)
        ConversationMessage.objects.bulk_create(
            [
                ConversationMessage(
                    conversation=conversation,
                    role=message["role"],
                    content=message["content"],
                )
                for message in messages
            ]
        )
        if messages:
            conversation.updated_at = timezone.now()
            conversation.save(update_fields=["updated_at"])


def load_conversation_messages(
    *,
    conversation_id: UUID,
) -> list[dict[str, object]]:
    conversation = _get_local_conversation(conversation_id=conversation_id)
    return [
        {"role": message.role, "content": message.content}
        for message in conversation.messages.all()
    ]


def list_conversations(
    *,
    workspace_path: Path | None = None,
) -> list[ConversationSummary]:
    conversations = Conversation.objects.select_related("memory_space").filter(
        memory_space__owner__username=LOCAL_USERNAME,
    )
    if workspace_path is not None:
        conversations = conversations.filter(
            memory_space__workspace_path=str(workspace_path.resolve()),
        )

    return [
        ConversationSummary(
            id=conversation.id,
            title=conversation.title or "New conversation",
            workspace_path=Path(conversation.memory_space.workspace_path),
            workspace_available=Path(conversation.memory_space.workspace_path).is_dir(),
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )
        for conversation in conversations.order_by("-updated_at", "-created_at")
    ]


def resume_conversation(
    *,
    conversation_id: UUID,
    workspace_path: Path,
) -> Conversation:
    conversation = _get_local_conversation(conversation_id=conversation_id)
    if conversation.memory_space.workspace_path != str(workspace_path.resolve()):
        raise ConversationNotFoundError(
            f"Conversation {conversation_id} was not found in this workspace."
        )
    return conversation


def prepare_conversation_runtime(
    *,
    conversation_id: UUID,
) -> ConversationRuntimeContext:
    conversation = _get_local_conversation(conversation_id=conversation_id)
    workspace_path = Path(conversation.memory_space.workspace_path)
    if not workspace_path.is_dir():
        raise WorkspaceUnavailableError(f"Workspace {workspace_path} is unavailable.")
    return ConversationRuntimeContext(
        conversation_id=conversation.id,
        workspace_path=workspace_path,
        memory_context=MemoryContext(
            user_id=str(conversation.memory_space.owner_id),
            space_id=str(conversation.memory_space_id),
        ),
    )


def _visible_assistant_text(
    messages: Sequence[dict[str, object]],
) -> str:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if not isinstance(content, list):
            return ""
        parts = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        if parts:
            return "\n".join(parts)
        return ""
    return ""


def run_conversation_turn(
    *,
    conversation_id: UUID,
    query: str,
    runner_factory: Callable[[ConversationRuntimeContext], AgentRunner],
) -> TurnResult:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query must not be empty")

    runtime_context = prepare_conversation_runtime(conversation_id=conversation_id)
    append_conversation_message(
        conversation_id=conversation_id,
        message={"role": "user", "content": normalized_query},
    )
    messages = load_conversation_messages(conversation_id=conversation_id)
    runner = runner_factory(runtime_context)
    generated_messages = runner.run(
        messages=messages,
        latest_user_query=normalized_query,
    )
    assistant_text = _visible_assistant_text(generated_messages)
    if not assistant_text:
        raise AgentResponseError("Agent returned no assistant text")

    append_conversation_messages(
        conversation_id=conversation_id,
        messages=generated_messages,
    )
    conversation = _get_local_conversation(conversation_id=conversation_id)
    return TurnResult(
        conversation_id=conversation.id,
        title=conversation.title or "New conversation",
        assistant_text=assistant_text,
    )
