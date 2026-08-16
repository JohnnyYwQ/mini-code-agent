import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from anthropic.types import ToolParam
from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()


MAX_ROUNDS = 500


def valid_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


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


def safe_path(p: str, *, workspace: Path | None = None) -> Path:
    """
    transform string path to Path path.

    make sure path not escape workdir

    get str as input Path as output
    """
    workspace_root = (workspace or WORKDIR).resolve()
    path = (workspace_root / p).resolve()
    if not path.is_relative_to(workspace_root):
        raise ValueError(f"Path eacaped workspace: {path}")
    return path


def run_bash(command: str, *, workspace: Path | None = None) -> str:
    """
    run bash command in shell by subprocess.

    block dangerous command.

    return detail error info:
        timeout
        other error

    get command as input strout+stderr as output
    """
    try:
        r = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=workspace or WORKDIR,
        )
        out = str(r.stdout + r.stderr).strip()
        return out
    except subprocess.TimeoutExpired:
        return "Error: Timeout(120)"


def run_read(
    path: str,
    limit: int = 10,
    *,
    workspace: Path | None = None,
) -> str:
    """
    read file content in workspace.

    we need file content, so path must be exist in workspace
    and be a file

    file content is str, but we need limit lines of content
    so content change as a pipeline:
        str -> lines -> limit lines -> str

    path and limit lines as input, file content as output
    """
    f = safe_path(path, workspace=workspace)
    if not f.exists():
        raise ValueError(f"File not found {path}")
    if not f.is_file():
        raise ValueError(f"Path is not a file {path}")
    if limit < 0:
        raise ValueError("limit must be non-negative.")
    lines = f.read_text().splitlines()
    if limit and limit < len(lines):
        lines = lines[:limit] + [f"... {len(lines) - limit} more lines."]
    return "\n".join(lines)


def run_write(
    path: str,
    text: str,
    *,
    workspace: Path | None = None,
) -> str:
    """
    write text in file.

    make sure path exist, if not, make it

    path and text as input, str of done or not as output
    """
    try:
        f = safe_path(path, workspace=workspace)

        f.parent.mkdir(exist_ok=True, parents=True)

        f.write_text(text)

        return f"{len(text)} bytes wrote"
    except Exception as e:
        return f"Error: {e}"


def run_edit(
    path: str,
    old_text: str,
    new_text: str,
    *,
    workspace: Path | None = None,
) -> str:
    """
    edit file content: replace old text by new text

    file must exist and old text must exist

    path, old_text, new_text as input, edit result as output
    """
    try:
        f = safe_path(path, workspace=workspace)
        if not f.exists():
            raise ValueError(f"file not found: {path}.")

        if not f.is_file():
            raise ValueError(f"Invalid path{path}.")
        content = f.read_text()

        if not old_text:
            raise ValueError("old text can not be empty.")
        if old_text not in content:
            raise ValueError(f"text not found: {old_text} in {path}.")

        f.write_text(content.replace(old_text, new_text, 1))
        return f"Edited file{path}."

    except Exception as e:
        return f"Error: {e}."


def run_glob(pattern: str, *, workspace: Path | None = None) -> str:
    import glob as g

    try:
        workspace_root = (workspace or WORKDIR).resolve()
        results = []
        for match in g.glob(pattern, root_dir=workspace_root, recursive=True):
            if (workspace_root / match).resolve().is_relative_to(workspace_root):
                results.append(match)
        return "\n".join(results) if results else "(no matches)"
    except Exception as e:
        return f"Error: {e}"


TOOLS: list[ToolParam] = [
    {
        "name": "bash",
        "description": "Run a bash command in a shell.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "read file content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "limit": {"type": "integer", "minimum": 0},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "write text in a file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "text": {"type": "string"}},
            "required": ["path", "text"],
        },
    },
    {
        "name": "edit_file",
        "description": "edit a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "glob",
        "description": "Find files matching a glob pattern",
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
            "required": ["pattern"],
        },
    },
    {
        "name": "todo",
        "description": "update task list. Track step in multi-step tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "text": {"type": "string"},
                            "state": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "done"],
                            },
                        },
                        "required": ["id", "text", "state"],
                    },
                }
            },
            "required": ["items"],
        },
    },
    {
        "name": "load_skill",
        "description": "Load the full content of a skill by name.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "compact",
        "description": "Summarize earlier conversation to free context space.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


# permission check
DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if"]
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777"]


def permission_hook(
    block,
    *,
    workspace: Path | None = None,
    confirm_destructive: Callable[[object], bool] | None = None,
):
    """PreToolUse: s03 check_permission() logic moved here."""
    if block.name == "bash":
        for pattern in DENY_LIST:
            if pattern in block.input.get("command", ""):
                print(f"\n\033[31m⛔ Blocked: '{pattern}'\033[0m")
                return "Permission denied by deny list"
        for kw in DESTRUCTIVE:
            if kw in block.input.get("command", ""):
                print("\n\033[33m⚠  Potentially destructive command\033[0m")
                print(f"   Tool: {block.name}({block.input})")
                allowed = (
                    confirm_destructive(block)
                    if confirm_destructive is not None
                    else input("   Allow? [y/N] ").strip().lower() in ("y", "yes")
                )
                if not allowed:
                    return "Permission denied by user"
    if block.name in ("write_file", "edit_file"):
        path = block.input.get("path", "")
        try:
            safe_path(path, workspace=workspace)
        except ValueError:
            return "Permission denied: path outside workspace"
    return None


def log_hook(block):
    """PreToolUse: log every tool call."""
    args_preview = str(list(block.input.values())[:2])[:60]
    print(f"\033[90m[HOOK] {block.name}({args_preview})\033[0m")
    return None


def large_output_hook(block, output):
    """PostToolUse: warn on large output."""
    if len(str(output)) > 100000:
        print(
            f"\033[33m[HOOK] ⚠ Large output from {block.name}: {len(str(output))} chars\033[0m"
        )
    return None


# Stop hook: print summary when loop is about to exit
def summary_hook(messages: list):
    tool_count = sum(
        1
        for m in messages
        for b in (m.get("content") if isinstance(m.get("content"), list) else [])
        if isinstance(b, dict) and b.get("type") == "tool_result"
    )
    print(f"\033[90m[HOOK] Stop: session used {tool_count} tool calls\033[0m")
    return None


if __name__ == "__main__":
    import argparse
    import sys
    from uuid import UUID

    import django  # type: ignore[import-untyped]

    django_root = Path(__file__).resolve().parents[1]
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
        raise SystemExit(0)

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
