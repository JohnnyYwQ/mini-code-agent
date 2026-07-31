"""
Agent with tools:
    bash
    read
    write
    edit
    todo
"""

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from anthropic import Anthropic
from anthropic.types import ToolParam
from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.history import FileHistory

if __package__:
    from .compaction import ContextCompactor
    from .skills import SkillManager
    from .todo import TodoManager
else:
    from compaction import ContextCompactor
    from skills import SkillManager
    from todo import TodoManager

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL: str = os.getenv("MODEL_ID", "")
API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
BASE_URL = os.getenv("ANTHROPIC_BASE_URL")


MAX_ROUNDS = 500


def validate_anthropic_config():
    if not MODEL:
        raise RuntimeError("MODEL_ID is required")
    if not API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is required")
    if BASE_URL and not valid_http_url(BASE_URL):
        raise RuntimeError("ANTHROPIC_BASE_URL must be a valid http(s) URL")


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

SKILL_DIR = WORKDIR / ".skills"


def request_compaction_summary(prompt: str) -> str:
    """Ask the configured model to summarize a serialized history."""
    response = client.messages.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
    )
    return (
        "".join(block.text for block in response.content if hasattr(block, "text"))
        or "empty summary"
    )


CONTEXT_COMPACTOR = ContextCompactor(
    transcript_dir=WORKDIR / ".transcription",
    tool_results_dir=WORKDIR / ".tool_result",
    summarize=request_compaction_summary,
)


def safe_path(p: str) -> Path:
    """
    transform string path to Path path.

    make sure path not escape workdir

    get str as input Path as output
    """
    workspace = WORKDIR.resolve()
    path = (workspace / p).resolve()
    if not path.is_relative_to(workspace):
        raise ValueError(f"Path eacaped workspace: {path}")
    return path


def run_bash(command: str) -> str:
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
            cwd=WORKDIR,
        )
        out = str(r.stdout + r.stderr).strip()
        return out
    except subprocess.TimeoutExpired:
        return "Error: Timeout(120)"


def run_read(path: str, limit: int = 10) -> str:
    """
    read file content in workspace.

    we need file content, so path must be exist in workspace
    and be a file

    file content is str, but we need limit lines of content
    so content change as a pipeline:
        str -> lines -> limit lines -> str

    path and limit lines as input, file content as output
    """
    f = safe_path(path)
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


def run_write(path: str, text: str) -> str:
    """
    write text in file.

    make sure path exist, if not, make it

    path and text as input, str of done or not as output
    """
    try:
        f = safe_path(path)

        f.parent.mkdir(exist_ok=True, parents=True)

        f.write_text(text)

        return f"{len(text)} bytes wrote"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    """
    edit file content: replace old text by new text

    file must exist and old text must exist

    path, old_text, new_text as input, edit result as output
    """
    try:
        f = safe_path(path)
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


def run_glob(pattern: str) -> str:
    import glob as g

    try:
        workspace = WORKDIR.resolve()
        results = []
        for match in g.glob(pattern, root_dir=workspace, recursive=True):
            if (workspace / match).resolve().is_relative_to(workspace):
                results.append(match)
        return "\n".join(results) if results else "(no matches)"
    except Exception as e:
        return f"Error: {e}"


def print_extract_text(messages_content):
    """
    get text from assistant response
    """
    if not isinstance(messages_content, list):
        return str(messages_content)
    text = "\n".join(
        block.text
        for block in messages_content
        if getattr(block, "type", None) == "text"
    )
    return text


TODO = TodoManager()
SKILL = SkillManager(SKILL_DIR)


def build_system() -> str:
    catalog = SKILL.list_skills()
    return (
        f"You are a coding agent at {WORKDIR}. "
        f"Skills available:\n{catalog}\n"
        "Use load_skill to get full details when needed."
    )


SYSTEM = build_system()

TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit", 10)),
    "write_file": lambda **kw: run_write(kw["path"], kw["text"]),
    "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "glob": lambda **kw: run_glob(kw["pattern"]),
    "todo": lambda **kw: TODO.update(kw["items"]),
    "load_skill": lambda **kw: SKILL.load_skill(kw["name"]),
}


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


# ═══════════════════════════════════════════════════════════
#  Hook System
# ═══════════════════════════════════════════════════════════
HookCallback = Callable[..., object | None]

HOOKS: dict[str, list[HookCallback]] = {
    "UserPromptSubmit": [],
    "PreToolUse": [],
    "PostToolUse": [],
    "Stop": [],
}


def register_hook(event: str, callback: HookCallback) -> None:
    HOOKS[event].append(callback)


def trigger_hooks(event: str, *args: object) -> object | None:
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:
            return result
    return None


# permission check
DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if"]
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777"]


def permission_hook(block):
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
                choice = input("   Allow? [y/N] ").strip().lower()
                if choice not in ("y", "yes"):
                    return "Permission denied by user"
    if block.name in ("write_file", "edit_file"):
        path = block.input.get("path", "")
        try:
            safe_path(path)
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


# UserPromptSubmit hook: log user input before it reaches the LLM
def context_inject_hook(query: str):
    print(f"\033[90m[HOOK] UserPromptSubmit: working in {WORKDIR}\033[0m")
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


register_hook("UserPromptSubmit", context_inject_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", summary_hook)


def agent_loop(messages: list):
    """
    Run the agent until stop using tool.

    set max round 500, raise runtime error if exceeded.

    Each loop:
    - call the model with the current messages
    - append the assistant response to message
    - execute any tool_use block returned by the model
    - manually calling todo reminder if didn't call it in 3 round
    - append tool_results block as new user message
    - continue so the model can observe tool results

    The messages list is mutated in place.
    """
    rounds_since_todo = 0
    validate_anthropic_config()
    for _ in range(MAX_ROUNDS):
        messages[:] = CONTEXT_COMPACTOR.prepare_for_model(messages)
        try:
            response = client.messages.create(
                model=MODEL,
                system=SYSTEM,
                tools=TOOLS,
                messages=messages,
                max_tokens=8000,
            )
        except Exception as e:
            raise RuntimeError(
                "Anthropic API request failed. Check MODEL_ID, ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, network, and model access."
            ) from e

        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            force = trigger_hooks("Stop", messages)
            if force:
                messages.append({"role": "user", "content": str(force)})
                continue
            return

        used_todo = False
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            blocked = trigger_hooks("PreToolUse", block)
            if blocked:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(blocked),
                    }
                )
                continue
            if block.name == "compact":
                messages[:] = CONTEXT_COMPACTOR.compact_history(messages[:-1])
                messages.append({"role": "assistant", "content": response.content})
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "[Compacted]. Conversation history has been summaried.",
                    }
                )
                continue

            handler = TOOL_HANDLERS.get(block.name)
            try:
                output = (
                    handler(**block.input) if handler else f"Unknown tool: {block.name}"
                )
            except Exception as e:
                output = f"Error: {e}"
            trigger_hooks("PostToolUse", block, output)
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": str(output)}
            )
            if block.name == "todo":
                used_todo = True
        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        if rounds_since_todo >= 3:
            tool_results.append(
                {"type": "text", "text": "<reminder>Update your todos</reminder>"}
            )
        messages.append({"role": "user", "content": tool_results})
    raise RuntimeError(f"Agent exceeded max rounds: {MAX_ROUNDS}")


if __name__ == "__main__":
    """
    whole agent service's entry which is a loop for multiple turn chat

    certain user input can break the loop
    """
    history = []
    while True:
        try:
            query = session.prompt(
                "\033[36mmini-code-agent >> \033[0m",
            )
        except (KeyboardInterrupt, EOFError):
            break
        if query.strip().lower() in ("q", "", "exit"):
            break
        trigger_hooks("UserPromptSubmit", query)
        history.append({"role": "user", "content": query})
        agent_loop(history)
        # Print the model's final text response
        response_content = history[-1]["content"]
        print_extract_text(response_content)
        print()
