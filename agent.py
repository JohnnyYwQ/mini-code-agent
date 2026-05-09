import os
import subprocess

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = os.getcwd()

client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

SYSTEM = f"You are a coding agent at {WORKDIR}. Use bash to solve tasks. Act, don't explain."

TOOLS = [{
    "name": "bash",
    "description": "Run a shell command.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}]



def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "reboot", "shutdown", "sudo"]
    if any(d in command for d in dangerous):
        return "Error: dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True,
                           cwd=WORKDIR, timeout=120)
    except subprocess.TimeoutExpired:
        return "Error: Timeout(120s)"
    except Exception as e:
        return f"Error: {e}"
    out = str(r.stdout + r.stderr)[:50000]
    return out


TOOLS_HANDLER = {
    "bash": lambda **kw: run_bash(kw["command"]),
}



def agent_loop(messages: list):
    while True:
    # Ask llm for response
        response = client.messages.create(
            model=MODEL, system=SYSTEM, tools=TOOLS,
            messages=messages, max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
    # Find tool_use response then call the tool
        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOLS_HANDLER.get(block.name)
                output = handler(**block.input) if handler else f"Invalid tool:{block.name}"
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": str(output)[:50000]})
    # Append tool output in message as user's input
        messages.append({"role": "user", "content": results})

if __name__ == "__main__":
    history = []
    while True:
    # User input
        try:
            query = input(">> ")
        except KeyboardInterrupt:
            break
        if query in ["", "q", "exit"]:
            break
    # Transform user input to messages
        history.append({"role": "user", "content": query})
    # Call agent loop
        agent_loop(history)
    # return agent answer
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
    
