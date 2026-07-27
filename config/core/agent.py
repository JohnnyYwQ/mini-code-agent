"""
Agent with tools:
    bash
    read
    write
    edit
    todo
    subagent
"""

import os
import subprocess
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from urllib.parse import urlparse
from dataclasses import dataclass
import yaml
import time
import json

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
TOOL_RESULTS_DIR = WORKDIR / ".tool_result"
TRANSCRIPTION = WORKDIR / ".transcription"
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.getenv("MODEL_ID")
API_KEY = os.getenv("ANTHROPIC_API_KEY")
BASE_URL = os.getenv("ANTHROPIC_BASE_URL")

SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools to solve tasks. Act, don't explain.All destructive operations require user approval."
SUBAGENT_SYSTEM = f"You are a coding subagent at {WORKDIR}. Complete the given task, then summarize your findings."
MAX_ROUNDS = 500
PERSIST_THRESHOLD = 4000
KEEP_RECENT = 30

def create_session_id():
    """
    create a unique session id
    """


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


# ═══════════════════════════════════════════════════════════
#  Skill System
# ═══════════════════════════════════════════════════════════

SKILL_DIR = Path("WORKDIR / .skills")

@dataclass
class Skill:
    name: str
    description: str
    path: Path
    content: str | None = None

class SKillManager:
    """
    manage skills
    """

    def __init__(self, skill_dir):
        self.skill_dir: Path = Path(skill_dir)
        self.registry: dict[str, Skill] = {}
        self._scan_skills()


    def _parser_frontmatter(self, text: str):
        """
        parser YAML frontmatter
        """
        if not text.startswith("---"):
            return {}, text
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}, text
        try:
            meta = yaml.safe_load(parts[1])
        except yaml.YAMLError:
            meta = {}
        return meta, parts[2]

    def list_skills(self):
        """
        list all skills' metadata for llm
        """
        return [{"name": skill.name, "description": skill.description} for skill in self.registry.values()]


    def _scan_skills(self):
        """
        scan all skills
        """
        for d in self.skill_dir.iterdir():
            if not d.is_dir():
                continue
            manifest = d / "SKILL.md"
            if not manifest.exists():
                continue
            text = manifest.read_text()
            meta, content = self._parser_frontmatter(text)
            name = meta.get("name", d.name)
            description = meta.get("description", text.split("\n")[0].lstrip("#").strip())
            if not (name and description):
                continue
            skill = Skill(name=name,
                        description=description,
                        path = manifest, 
                        content = content)
            self.registry[name] = skill

        

    def load_skill(self, name: str):
        """
        load a skill from registry by name
        """
        if name not in self.registry.keys():
            return "skill not found"
        return self.registry[name].content

# ═══════════════════════════════════════════════════════════
#  messages compress
# ═══════════════════════════════════════════════════════════
def estimate_token(messages: list):
    """
    estimate tokens
    """
    return len(str(messages)) // 4


def collect_tool_results(messages: list):
    """
    collect all tool results
    """
    tool_results = []
    for mid, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for bid, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                tool_results.append((mid, bid, block))

    return tool_results

def micro_compact(messages: list):
    """
    compact history messages tool result
    """
    results = collect_tool_results(messages)
    if len(results) <= KEEP_RECENT:
        return messages
    for result in results[:-KEEP_RECENT]:
        if len(result.get("content", "")) > 120:
            result["content"] = "[Earlier tool result compacted, rerun if needed]"
    return messages 
        
        

def tool_result_budget(messages: list, max_bytes: int = 200_000):
    """
    persist long tool result then replace it by placeholder, just for newest message
    """ 
    last_message = messages[-1] if messages else None
    if not last_message or last_message.get("role") != "user" or not isinstance(last_message.get("content"), list):
        return messages
    content = last_message.get("content")
    blocks = [(index, block) for index, block in enumerate(content) if isinstance(block, dict) and block.get("type") == "tool_result"]
    total = [sum(len(str(b.get("content", ""))) for _, b in blocks)]    
    if total <= max_bytes:
        return messages
    ranked = sorted(blocks, lambda p: len(p[1].get("content", "")), reverse=True)
    for _, block in ranked:
        if total <= max_bytes:
            break
        tool_use_id = block.get("tool_use_id")
        persist_large_output(tool_use_id, block.get("content", ""))
        total = [sum(len(b.get("content")) for _, b in blocks)]
    return messages


def persist_large_output(tool_use_id: str, output: str):
    """
    save output into disk file
    """
    if len(output) <= PERSIST_THRESHOLD:
        return output
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    p = TOOL_RESULTS_DIR / f"tool_result_{tool_use_id}"
    if not p.exists():
        p.write_text(output)
    return f"<persist large output>\nFull output:{p}\nPreview:\n{output[:2000]}\n</persist large output>"
    

def snip_compact(messages: list, max_messages: int = 50):
    """
    replace middle messages by placeholder
    """
    if len(messages) < max_messages:
        return messages
    keep_head, keep_tail = 3, max_messages - 3
    snipped = len(messages) - keep_head - keep_tail
    return messages[:keep_head] + [{"role": "user", "content": f"snipped {snipped} messages"}] + messages[-keep_tail:]
    

def write_transcript(messages: list):
    """
    save all messages into disk before llm summary
    """
    TRANSCRIPTION.mkdir(parents=True, exist_ok=True)
    path = WORKDIR / TRANSCRIPTION / f"transcription_{int(time.time)}.json"
    with path.open("w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    return path

def summary_history(messages: list):
    """
    call llm to summary history
    """
    conversation = json.dump(messages, default=str)[:80000]
    prompt = ("Summarize this coding-agent conversation so work can continue.\n"
              "Preserve: 1. current goal, 2. key findings/decisions, 3. file read/changed,"
              "4. remaining work, 5. user constrains\n Be compact but concret" + conversation)
    response = client.messages.create(model=MODEL, messages=prompt, max_tokens=2000)
    return "".join(block.text for block in response.content if hasattr(block, "text")) or "empty summary"

def auto_compact(messages: list):
    """
    replace messages by llm history summary with compacted tips
    """
    write_transcript(messages)
    print("[Transcripted]")
    summary = summary_history(messages)
    return {"role": "user", "content": f"[Compacted]\n\n{summary}"}

def reactive_compact(messages: list):
    """
    emergency compact, replace messages by llm history summary + last 5 messages
    """
    write_transcript(messages)
    summary = summary_history(messages)
    return [{"role": "user", "content": f"[Reactive compacted]\n\n{summary}"}, *messages[-5:]]
            
class TodoManager:
    """
    In-memory todo list for the agent.

    Responsibilites:
    - store current items
    - validate todo update from the model
    - allow only one in_progress item
    - render the todo list as text for tool_result

    Item state must be one of:
    - pending
    - in_progress
    - done

    List is capped at 20 items
    """
    def __init__(self):
        self.items = []
    
    def update(self, items: list) -> str:
        """
        update items by llm's response

        only one task can be in progress
        """
        if len(items) > 20:
            raise ValueError("Max 20 todos allowed")
        validated = []
        in_progress_count = 0
        for i, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            state = str(item.get("state", "pending")).lower()
            item_idx = str(item.get("id", str(i + 1)))
            if not text:
                raise ValueError(f"Item {item_idx}: text is required")
            if state not in ["pending", "in_progress", "done"]:
                raise ValueError(f"Item {item_idx}: state must be in pending, in_progress, done")
            if state == "in_progress":
                in_progress_count += 1
            validated.append({"id": item_idx, "text": text, "state": state})
        if in_progress_count > 1:
            raise ValueError("only one task can be in progress")
        self.items = validated
        return self.render()
    
    def render(self) -> str:
        """
        Render the current todo list as text for the tool_result.

        Each item is shown with a status marker and the final line shows
        completed count.
        """
        if not self.items:
            return "no todos"
        lines = []
        for item in self.items:
            marker = {"pending": "[]", "in_progress": "[>]", "done": "[x]"}[item["state"]]
            lines.append(f"{marker}: #{item['id']}: {item['text']}")
        done = sum(1 for t in self.items if t["state"] == "done")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)


def safe_path(p: str) -> Path:
    """
    transform string path to Path path.
    
    make sure path not escape workdir

    get str as input Path as output
    """
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
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
        r = subprocess.run(command, shell=True, capture_output=True,
                           text=True, timeout=120, cwd=WORKDIR)
        out = str(r.stdout + r.stderr).strip()
        return out[:50000]
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
            raise ValueError(f"Error: file not found: {path}")

        if not f.is_file():
            raise ValueError(f"Invalid path{path}")
        content = f.read_text()

        if not old_text in content:
            raise ValueError(f"Error: text not found: {old_text} in {path}")
        
        f.write_text(content.replace(old_text, new_text, 1))
        return f"Edited file{path}"

    except Exception as e:
        return f"Error: {e}"

def run_glob(pattern: str) -> str:
    import glob as g
    try:
        results = []
        for match in g.glob(pattern, root_dir=WORKDIR):
            if (WORKDIR/ match).resolve().is_relative_to(WORKDIR):
                results.append(match)
        return "\n".join(results) if results else "(no matches)"
    except Exception as e:
        return f"Error: {e}"

def run_subagent(prompt: str) -> str:
    """
    run a subagent to do the task,

    if task is too complex, parent agent will split it to micro
    task, then let subagent do it, so subagent only need
    to focus on concret task, history is not necessary.

    Diff from agent:
    - limited loops
    - messages in subagent don't change message in agent
    - take parent agent's prompt only append summary
      as user messages for parent agent

    """
    submessages = [{"role": "user", "content": prompt}]
    for _ in range(30):
        response = client.messages.create(
            model=MODEL,
            system=SUBAGENT_SYSTEM,
            tools=CHILD_TOOLS,
            messages=submessages,
            max_tokens=8000,
        )
        
        submessages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            break
        
        results = []

        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name) 
                output = handler(**block.input) if handler else f"Tool not found: {block.name}"
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": str(output)[:50000]})
        submessages.append({"role": "user", "content": results})
    return "".join(b.text for b in response.content if hasattr(b, "text")) or "(no summary)"

TODO = TodoManager()

TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit", "10")),
    "write_file": lambda **kw: run_write(kw["path"], kw["text"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "glob":       lambda **kw: run_glob(kw["pattern"]),
    "todo":       lambda **kw: TODO.update(kw["items"]),
    "task":       lambda **kw: run_subagent(kw["prompt"]),
}


CHILD_TOOLS = [
    {
        "name": "bash", "description": "Run a bash command in a shell.",
        "input_schema": {"type": "object",
                        "properties": {"command": {"type": "string"}},
                        "required": ["command"]}
    },
    {
        "name": "read_file", "description": "read file content.",
        "input_schema": {"type": "object",
                        "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
                        "required": ["path"]}
    },
    {
        "name": "write_file", "description": "write text in a file.",
        "input_schema": {"type": "object",
                        "properties": {"path": {"type": "string"}, "text": {"type": "string"}},
                        "required": ["path", "text"]}
    },
    {
        "name": "edit_file", "description": "edit a file.",
        "input_schema": {"type": "object",
                         "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
                         "required": ["path", "old_text", "new_text"]},
    },
    {
        "name": "glob", "description": "Find files matching a glob pattern",
        "input_schema": {"type": "object",
                         "properties": {"pattern": {"type": "string"}},
                         "required": ["pattern"],
                        },
    },
]

PARENT_TOOLS = CHILD_TOOLS + [
    {
        "name": "todo", "description": "update task list. Track step in multi-step tasks.",
        "input_schema": {"type": "object",
                         "properties": {"items": {"type": "array",
                                                  "items": {"type": "object",
                                                            "properties": {"id": {"type": "integer"}, "text": {"type": "string"}, "state": {"type": "string", "enum": ["pending", "in_progress", "done"]}},
                                                            "required": ["id", "text", "state"]}}},
                         "required": ["items"]},
    },
    {
        "name": "task", "description": "Spawn a subagent with fresh context. It shares the filesystem but not conversation history.",
        "input_schema": {"type": "object",
                         "properties": {"prompt": {"type": "string"}, "description": {"type": "string", "description": "Short description of the task"}},
                         "required": ["prompt"]}
    }
]

# ═══════════════════════════════════════════════════════════
#  Hook System 
# ═══════════════════════════════════════════════════════════

HOOKS = {"UserPromptSubmit": [],
         "PreToolUse": [],
         "PostToolUse": [],
         "Stop": []}

def registry_hook(event: str, callback):
    HOOKS[event].append(callback)

def trigger_hooks(event:str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:
            return result
    return None

# permission check
DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if"]
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777"]

def permission_hook(block):
    """
    for bash tool
    """
    if block.name == "bash":
        if any(command in DENY_LIST for command in block.input):
            return "Error: Dangerous command blocked."
        if any(command in DESTRUCTIVE for command in block.input):
            isallowed = input("Allow? Yes/No").strip().lower()
            if isallowed == "yes":
                return True
            else:
                return "User stoped."



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
        try:
            response = client.messages.create(
                model=MODEL,
                system=SYSTEM,
                tools=PARENT_TOOLS,
                messages=messages,
                max_tokens=8000,
            )
        except Exception as e:
            raise RuntimeError(
                "Anthropic API request failed. Check MODEL_ID, ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, network, and model access." 
            ) from e
        
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        used_todo = False
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"\033[33m> {block.name}\033[0m")
                if not check_permission(block):
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                         "content": "Permission denied."})
                    continue
                handler = TOOL_HANDLERS.get(block.name)
                if block.name == "task":
                    desc = block.input.get("description", "subtask")
                    prompt = block.input.get("prompt", "")
                    print(f"> task({desc}): {prompt}")
                try:
                    output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                except Exception as e:
                    output = f"Error: {e}"
                tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                            "content": str(output)[:40000]})
                if block.name == "todo":
                    used_todo = True
        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        if rounds_since_todo >= 3:
            tool_results.append({"type": "text", "text": "<reminder>Update your todos</reminder>"})
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
            query = input("\033[36ms02 >> \033[0m")
        except (KeyboardInterrupt, EOFError):
                break
        if query.strip().lower() in ("q", "", "exit"):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        # Print the model's final text response
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if getattr(block, "type", None) == "text":
                    print(block.text)
            print()