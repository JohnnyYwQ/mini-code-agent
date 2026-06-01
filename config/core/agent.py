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

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools to solve tasks. Act, don't explain."
SUBAGENT_SYSTEM = f"You are a coding subagent at {WORKDIR}. Complete the given task, then summarize your findings."

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
    dangerous = ["sudo", "rm -rf /", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return f"Error: dangerous command blocked:{command}"
    
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


def agent_loop(messages: list):
    """
    Run the agent until stop using tool.

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
    while True:
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            tools=PARENT_TOOLS,
            messages=messages,
            max_tokens=8000,
        )

        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        used_todo = False
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
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

if __name__ == "__main__":
    """
    whole agent service's entry which is a loop for multiple turn chat

    certain user input can break the loop
    """
    history = []
    while True:
        try:
            query = input(">: ")
            if query in ["q", "", "exit"]:
                break
        except (KeyboardInterrupt, EOFError):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
            print()