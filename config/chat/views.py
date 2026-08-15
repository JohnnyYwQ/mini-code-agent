import json
from collections import OrderedDict
from pathlib import Path
from uuid import UUID

from django.http import Http404, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from chat.application import (
    AgentResponseError,
    ConversationNotFoundError,
    WorkspaceUnavailableError,
    list_conversations,
    load_conversation_messages,
    require_available_workspace,
    run_conversation_turn,
    start_conversation,
)
from chat.composition import build_web_runner

DEFAULT_WEB_WORKSPACE = Path.cwd().resolve()


def brief_error(exc: Exception) -> str:
    message = str(exc).splitlines()[0].strip()
    return message[:300] or exc.__class__.__name__


def extract_assistant_text(message: object) -> str | None:
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content.strip() or None
    if not isinstance(content, list):
        return None

    parts = []
    for block in content:
        text = block.get("text") if isinstance(block, dict) else None
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts) or None


def _visible_transcript(messages: list[dict[str, object]]) -> list[dict[str, str]]:
    visible = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "user" and isinstance(content, str) and content.strip():
            visible.append({"role": "user", "content": content.strip()})
        elif role == "assistant":
            text = extract_assistant_text(message)
            if text:
                visible.append({"role": "assistant", "content": text})
    return visible


def _conversation_id(raw_id: object) -> UUID | None:
    if not isinstance(raw_id, str):
        return None
    try:
        return UUID(raw_id)
    except ValueError:
        return None


def index(request):
    summaries = list_conversations()
    selected_id = _conversation_id(request.GET.get("conversation"))
    if request.GET.get("conversation") and selected_id is None:
        raise Http404("Conversation not found")

    selected = None
    if selected_id is not None:
        selected = next(
            (summary for summary in summaries if summary.id == selected_id),
            None,
        )
        if selected is None:
            raise Http404("Conversation not found")
    elif summaries:
        selected = summaries[0]

    grouped: OrderedDict[Path, list] = OrderedDict()
    for summary in summaries:
        grouped.setdefault(summary.workspace_path, []).append(summary)
    conversation_groups = [
        {
            "workspace_path": workspace_path,
            "conversations": conversations,
            "active": bool(selected and selected.workspace_path == workspace_path),
        }
        for workspace_path, conversations in grouped.items()
    ]

    messages = (
        _visible_transcript(load_conversation_messages(conversation_id=selected.id))
        if selected
        else []
    )
    return render(
        request,
        "chat/index.html",
        {
            "conversation_groups": conversation_groups,
            "selected_conversation": selected,
            "messages": messages,
            "workspace_unavailable": bool(
                selected and not selected.workspace_available
            ),
        },
    )


def new_conversation(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    selected_id = _conversation_id(request.POST.get("conversation_id"))
    if request.POST.get("conversation_id") and selected_id is None:
        raise Http404("Conversation not found")
    try:
        workspace_path = (
            require_available_workspace(conversation_id=selected_id)
            if selected_id is not None
            else DEFAULT_WEB_WORKSPACE
        )
    except ConversationNotFoundError as exc:
        raise Http404("Conversation not found") from exc
    except WorkspaceUnavailableError as exc:
        raise Http404("Workspace unavailable") from exc

    conversation = start_conversation(workspace_path=workspace_path)
    return redirect(f"{reverse('chat:index')}?conversation={conversation.id}")


def chat_api(request):
    if request.method != "POST":
        response = JsonResponse(
            {"ok": False, "error": "Method not allowed"},
            status=405,
        )
        response["Allow"] = "POST"
        return response
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    if not isinstance(data, dict):
        return JsonResponse(
            {"ok": False, "error": "Message is required"},
            status=400,
        )
    raw_message = data.get("message")
    if not isinstance(raw_message, str) or not raw_message.strip():
        return JsonResponse(
            {"ok": False, "error": "Message is required"},
            status=400,
        )
    conversation_id = _conversation_id(data.get("conversation_id"))
    if conversation_id is None:
        return JsonResponse(
            {"ok": False, "error": "Conversation is required"},
            status=400,
        )

    try:
        result = run_conversation_turn(
            conversation_id=conversation_id,
            query=raw_message,
            runner_factory=build_web_runner,
        )
    except ConversationNotFoundError:
        return JsonResponse(
            {"ok": False, "error": "Conversation not found"},
            status=404,
        )
    except WorkspaceUnavailableError as exc:
        return JsonResponse(
            {"ok": False, "error": brief_error(exc)},
            status=409,
        )
    except AgentResponseError as exc:
        return JsonResponse(
            {"ok": False, "error": brief_error(exc)},
            status=502,
        )
    except Exception as exc:
        return JsonResponse(
            {"ok": False, "error": f"Agent failed: {brief_error(exc)}"},
            status=500,
        )

    return JsonResponse(
        {
            "ok": True,
            "conversation_id": str(result.conversation_id),
            "title": result.title,
            "user": raw_message.strip(),
            "assistant": result.assistant_text,
            "tool_trace": [],
        }
    )
