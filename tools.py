from pathlib import Path
import subprocess
from typing import Any

class BaseTool:
    """
    BaseTool class for all tools exposed to model.

    A Tool have two sides:

    1. Model-facing-side:
        name / description / input_schema / are sent to LLM
        The model reads them and returns tool_use blocks.

    2. Runtime-facing side:
        call() is used by agent_loop to excute a tool_use.
        It runs the standard lifecycle:
        validate -> check_permission -> run -> format_result.

    Subclasses should usually override:
        validate()
        check_permission()
        run()

    Subclasses usually not override:
        call()
    """
    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {},
    }
    is_read_only: bool = False
    is_destructive: bool = False
    max_ouput_chars: int = 50000

    def to_anthropic_tool(self) -> dict[str, Any]:
        """
        Convert this Tool object into the dict format expected by
        client.messages.create(..., tools=[...]).
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
    
    def validate(self, args: dict[str, Any]) -> dict[str: Any]:
        """
        Validate and normalize model-provided tool input.

        args comes from block.input.
        For example:
            {"command": "ls"}

        Base class only checks that args is a dict.
        Specific tools should check their own required fields.
        """
        if not isinstance(args, dict):
            raise ValueError("tool input must be an object")
        return args
    
    def check_permission(self, args: dict[str, Any]) -> tuple[bool, str]:
        """
        Decide whether this tool call is allowed.

        Return: 
            (True, "") if allowed
            (False, "reason") if blocked

        Base class allows everything.
        Specific tools can override this.
        """
        return True, ""
    
    def run(self, args: dict[str, Any]) -> str:
        """
        Actually execute the tool.

        Base tool does not know how to run anything.
        Every concrete tool must implement this.
        """
        raise NotImplementedError

    def format_result(self, output: Any) -> str:
        """
        Convert tool output into text that can be sent back to the model.
        """
        return str(output)[:self.max_ouput_chars]
    
    def call(self, args: dict[str, Any]) -> str:
        """
        The single entrypoint used by agent_loop.

        Do not duplicate this flow in every tool.
        Tools customize behavior by overriding validate/check_permission/run.
        """
        try:
            args = self.validate(args)
            allowed, reason = self.check_permission(args)
            if not allowed:
                return f"Error: {reason}"
            
            output = self.run(args)
            return self.format_result(output)
        except Exception as e:
            return f"Error: {e}"
        
class BashTool(BaseTool):
    """
    Tool that let agent run shell commands.

    The model sees this as:
        name = "bash"
        input_schema = {"command": "string"}
    
    The runtime executes it through:
        BashTool.call({"command": "pwd"})
    """

    name = "bash"
    description = "Run a shell command."
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string"}
        },
        "required": ["command"]
    }
    is_destructive = True
    
    def __init__(self, workdir: str, timeout: int = 120):
        """
        workdir and timeout are runtime configuration.
        They are not provided by the model.
        """
        self.workdir = workdir
        self.timeout = timeout

    def valilate(self, args):
        """
        Bash requires:
            {"command": non-empty string}
        """
        args = super().validate(args)

        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        
        return {"command": command}
    
    def check_permission(self, args: dict) -> tuple[bool, str]:
        """
        Minimal Stage 1/2 safety check.
        This is not a full sanbox or permission system.
        """
        command = args["command"]
        dangerous = ["rm -rf /", "reboot", "shutdown", "sudo"]
        if any(d in command for d in dangerous):
            return False, "dangerous command blocked"

        return True, ""

    def run(self, args: dict) -> str:
        """
        Execute the shell command and return stdout + stderr
        """
        try:
            r = subprocess.run(
                args["command"],
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.workdir,
                timeout=self.timeout
            )
        except subprocess.TimeoutExpired:
            return f"Error: Timeout({self.timeout}s)"
        except Exception as e:
            return f"Error: {e}"

        output = r.stdout + r.stderr
        return output if output else "(no output)"
    
class ReadFileTool(BaseTool):
    """
    ReadFileTool is a direct action tool.

    It exposes file reading to the model as a tool_use:

        block.name = "read_file"
        block.input = {"path": "README.md", "limit": 100}

    Internally, it follows the standard Tool lifecycle inherited from Tool.call():
        
        validate -> check_permission -> run -> format_result

    This tool is read-only. It does not modify the workspace.

    The model only provides a relative file path and opthional line limit.
    The runtime owns the workspace boundary through self.workdir.
    """
    name = "read_file"
    description = "Read file contents."
    input_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}, 
                       "limit": {"type": "integer"}},
        "required": ["path"]
    }
    is_read_only = True
    max_ouput_chars = 50000
    
    def __init__(self, workdir: str):
        """
        workdir is runtime configuration.

        The model should not decide the filesystem root.
        The harness decides it and passes it into the tool.
        """
        self.workdir = Path(workdir).resolve()

def build_tool_registry(workdir: str) -> dict[str: BaseTool]:
    """
    Tool registry
    
    The registry is the bridge between model-facing tool names and 
    runtime-faceing Tool Objects.

    The model only returns:
        block.name = "bash"
        block.input = {"command": "pwd"}

    The runtime uses the registry to find the local executor:
        TOOL_REGISTRY["bash"] -> BashTool(...)
    
    agents.py owns the runtime configuration such as WORKDIR.
    tools.py owns the avaliable tool classes.
    Therefore agent.py passes WORKDIR into build_tool_registry()
    """
    return {
        "bash": BashTool(workdir)
    }

def build_anthropic_tools(tool_registry: dict[str: BaseTool]) -> list[dict]:
    """
    Anthropic tool schema builder

    client.messages.create(..., tools=...) does not receive Tool objects.
    It receives plain dictionaries containing name/description/input_schema.

    This function derives those API schemas from the same Tool objects used
    by the runtime, so the model-facing schema and local executor stay in sync.
    """
    return [
        tool.to_anthropic_tool()
        for tool in tool_registry.values()
    ]

    
if __name__ == "__main__":
    tool = BashTool(".")

    print("=== schema ===")
    print(tool.to_anthropic_tool())

    print("=== valid command ===")
    print(tool.call({"command": "pwd"}))

    print("=== invalid input ===")
    print(tool.call({"cmd": "pwd"}))

    print("=== dangerous command ===")
    print(tool.call({"command": "sudo ls"}))