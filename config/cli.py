"""Command-line adapter for Mini Code Agent Conversations."""

import argparse
import os
import sys
from pathlib import Path
from uuid import UUID

import django  # type: ignore[import-untyped]
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory

CLI_HISTORY = Path.home() / ".mini-code-agent" / "cli_history"
CLI_HISTORY.parent.mkdir(parents=True, exist_ok=True)

session = PromptSession[str](
    history=FileHistory(str(CLI_HISTORY)),
    auto_suggest=AutoSuggestFromHistory(),
    enable_history_search=True,
)
CLI_PROMPT = ANSI("\033[36mmini-code-agent >> \033[0m")


def visible_cli_history(
    messages: list[dict[str, object]],
) -> list[tuple[str, str]]:
    """Project a persisted transcript into the history shown by the CLI."""
    visible: list[tuple[str, str]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "user":
            if isinstance(content, str) and content.strip():
                visible.append(("user", content.strip()))
            continue

        if role != "assistant":
            continue
        if isinstance(content, str):
            if content.strip():
                visible.append(("assistant", content.strip()))
            continue
        if not isinstance(content, list) or any(
            isinstance(block, dict) and block.get("type") == "tool_use"
            for block in content
        ):
            continue

        parts = []
        for block in content:
            text = block.get("text") if isinstance(block, dict) else None
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        if parts:
            visible.append(("assistant", "\n".join(parts)))

    return visible


def print_cli_history(messages: list[dict[str, object]]) -> None:
    history = visible_cli_history(messages)
    if not history:
        return

    print("\nConversation history:")
    for role, text in history:
        label = "user" if role == "user" else "mini-code-agent"
        print(f"{label} >> {text}")
    print()


def main() -> None:
    django_root = Path(__file__).resolve().parent
    if str(django_root) not in sys.path:
        sys.path.insert(0, str(django_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()

    from chat.application import (
        ConversationNotFoundError,
        list_conversations,
        load_conversation_messages,
        resume_conversation,
        run_conversation_turn,
        start_conversation,
    )
    from chat.composition import build_cli_runner, close_production_memory

    parser = argparse.ArgumentParser(description="Mini Code Agent CLI")
    parser.add_argument(
        "--list",
        action="store_true",
        help="list resumable Conversations in the current workspace",
    )
    parser.add_argument(
        "--resume",
        metavar="CONVERSATION_ID",
        help="resume a Conversation from the current workspace",
    )
    args = parser.parse_args()
    cli_workspace = Path.cwd().resolve()

    if args.list:
        conversations = list_conversations(workspace_path=cli_workspace)
        if not conversations:
            print("No Conversations in this workspace.")
        for conversation in conversations:
            print(f"{conversation.id}  {conversation.title}")
        return

    if args.resume:
        try:
            resume_id = UUID(args.resume)
            conversation = resume_conversation(
                conversation_id=resume_id,
                workspace_path=cli_workspace,
            )
        except (ValueError, ConversationNotFoundError) as exc:
            parser.error(str(exc))
    else:
        conversation = start_conversation(workspace_path=cli_workspace)

    print(f"Conversation: {conversation.id}")
    if args.resume:
        print_cli_history(load_conversation_messages(conversation_id=conversation.id))
    try:
        while True:
            try:
                query = session.prompt(CLI_PROMPT)
            except (KeyboardInterrupt, EOFError):
                break
            if query.strip().lower() in ("q", "", "exit"):
                break
            try:
                result = run_conversation_turn(
                    conversation_id=conversation.id,
                    query=query,
                    runner_factory=build_cli_runner,
                )
            except Exception as exc:
                print(f"Error: {exc}")
                continue
            print(result.assistant_text)
            print()
    finally:
        close_production_memory()


if __name__ == "__main__":
    main()
