from pathlib import Path
import subprocess
from typing import Any

# class BaseTool:
#     """
#     BaseTool class for all tools exposed to model.

#     A Tool have two sides:

#     1. Model-facing-side:
#         name / description / input_schema / are sent to LLM
#         The model reads them and returns tool_use blocks.

#     2. Runtime-facing side:
#         call() is used by agent_loop to excute a tool_use.
#         It runs the standard lifecycle:
#         validate -> check_permission -> run -> format_result.

#     Subclasses should usually override:
#         validate()
#         check_permission()
#         run()

#     Subclasses usually not override:
#         call()
#     """
#     name: str = ""
#     description: str = ""
#     input_schema: dict[str, Any] = {
#         "type": "object",
#         "properties": {},
#     }
#     is_read_only: bool = False
#     is_destructive: bool = False
#     max_ouput_chars: int = 50000

#     def to_anthropic_tool(self) -> dict[str, Any]:
#         """
#         Convert this Tool object into the dict format expected by
#         client.messages.create(..., tools=[...]).
#         """
#         return {
#             "name": self.name,
#             "description": self.description,
#             "input_schema": self.input_schema,
#         }
    
#     def validate(self, args: dict[str, Any]) -> dict[str, Any]:
#         """
#         Validate and normalize model-provided tool input.

#         args comes from block.input.
#         For example:
#             {"command": "ls"}

#         Base class only checks that args is a dict.
#         Specific tools should check their own required fields.
#         """
#         if not isinstance(args, dict):
#             raise ValueError("tool input must be an object")
#         return args
    
#     def check_permission(self, args: dict[str, Any]) -> tuple[bool, str]:
#         """
#         Decide whether this tool call is allowed.

#         Return: 
#             (True, "") if allowed
#             (False, "reason") if blocked

#         Base class allows everything.
#         Specific tools can override this.
#         """
#         return True, ""
    
#     def run(self, args: dict[str, Any]) -> str:
#         """
#         Actually execute the tool.

#         Base tool does not know how to run anything.
#         Every concrete tool must implement this.
#         """
#         raise NotImplementedError

#     def format_result(self, output: Any) -> str:
#         """
#         Convert tool output into text that can be sent back to the model.
#         """
#         return str(output)[:self.max_ouput_chars]
    
#     def call(self, args: dict[str, Any]) -> str:
#         """
#         The single entrypoint used by agent_loop.

#         Do not duplicate this flow in every tool.
#         Tools customize behavior by overriding validate/check_permission/run.
#         """
#         try:
#             args = self.validate(args)
#             allowed, reason = self.check_permission(args)
#             if not allowed:
#                 return f"Error: {reason}"
            
#             output = self.run(args)
#             return self.format_result(output)
#         except Exception as e:
#             return f"Error: {e}"
        
# class BashTool(BaseTool):
#     """
#     Tool that let agent run shell commands.

#     The model sees this as:
#         name = "bash"
#         input_schema = {"command": "string"}
    
#     The runtime executes it through:
#         BashTool.call({"command": "pwd"})

#     BashTool runs commands inside the configured workdir
#     with a timeout, blocks a small set of obvious dangerous,
#     commands, and returns stdout + stderr as text.
#     """

#     name = "bash"
#     description = "Run a shell command."
#     input_schema = {
#         "type": "object",
#         "properties": {
#             "command": {"type": "string"}
#         },
#         "required": ["command"]
#     }
#     is_destructive = True
    
#     def __init__(self, workdir: str, timeout: int = 120):
#         """
#         workdir and timeout are runtime configuration.
#         They are not provided by the model.
#         """
#         self.workdir = workdir
#         self.timeout = timeout

#     def validate(self, args: dict):
#         """
#         Bash requires:
#             {"command": non-empty string}
#         """
#         args = super().validate(args)

#         command = args.get("command")
#         if not isinstance(command, str) or not command.strip():
#             raise ValueError("command must be a non-empty string")
        
#         return {"command": command}
    
#     def check_permission(self, args: dict) -> tuple[bool, str]:
#         """
#         Minimal Stage 1/2 safety check.
#         This is not a full sanbox or permission system.
#         """
#         command = args["command"]
#         dangerous = ["rm -rf /", "reboot", "shutdown", "sudo"]
#         if any(d in command for d in dangerous):
#             return False, "dangerous command blocked"

#         return True, ""

#     def run(self, args: dict) -> str:
#         """
#         Execute the shell command and return stdout + stderr
#         """
#         try:
#             r = subprocess.run(
#                 args["command"],
#                 shell=True,
#                 capture_output=True,
#                 text=True,
#                 cwd=self.workdir,
#                 timeout=self.timeout
#             )
#         except subprocess.TimeoutExpired:
#             return f"Error: Timeout({self.timeout}s)"
#         except Exception as e:
#             return f"Error: {e}"

#         output = r.stdout + r.stderr
#         return output if output else "(no output)"
    
# class ReadFileTool(BaseTool):
#     """
#     ReadFileTool is a direct action tool.

#     It exposes file reading to the model as a tool_use:

#         block.name = "read_file"
#         block.input = {"path": "README.md", "limit": 100}

#     Internally, it follows the standard Tool lifecycle inherited from Tool.call():
        
#         validate -> check_permission -> run -> format_result

#     This tool is read-only. It does not modify the workspace.

#     The model only provides a relative file path and opthional line limit.
#     The runtime owns the workspace boundary through self.workdir.
#     """
#     name = "read_file"
#     description = "Read file contents."
#     input_schema = {
#         "type": "object",
#         "properties": {"path": {"type": "string"}, 
#                        "limit": {"type": "integer"}},
#         "required": ["path"]
#     }
#     is_read_only = True
#     max_ouput_chars = 50000
    
#     def __init__(self, workdir: str):
#         """
#         workdir is runtime configuration.

#         The model should not decide the filesystem root.
#         The harness decides it and passes it into the tool.
#         """
#         self.workdir = Path(workdir).resolve()


#     def validate(self, args: dict) -> dict[str: Any]:
#         """
#         ReadFile requires:
#             {"path": no empty string}
#             {"path": no empty string, "limit": positive integer}
#         limit is optional.
#         """
#         args = super().validate(args)

#         path = args.get("path")
#         limit = args.get("limit")

#         if not isinstance(path, str) or not path.strip():
#             raise ValueError("path must be a non-empty string.")    

#         if not isinstance(limit, int):
#             raise ValueError("limit must be an integer.")   
        
#         return {
#             "path": path.strip(),
#             "limit": limit,
#             }
    
#     def check_permission(self, args) -> tuple[bool, str]:
#         """
#         Minimal permission check for reading a file.

#         Path coms from the model, so they are untrusted input.

#         This method prevent ReadFile from reading files outside the workspace
#         and rejects missing or non-file paths.

#         BaseTool.call() invokes this after validate() and before run().
#         """
#         try:
#             path = safe_path(self.workdir, args["path"])
#         except ValueError as e:
#             return False, str(e)
        
#         if not path.exists():
#             return False, f"file not found: {args['path']}"

#         if not path.is_file():
#             return False, f"not a file: {args['path']}"

#         return True, ""
    
#     def run(self, args) -> str:
#         """
#         read rile content and return it as text.

#         limit, if provided, means maximum number of lines.
#         """
#         path = safe_path(self.workdir, args["path"])
#         lines = path.read_text().splitlines()
#         limit = args.get("limit")
#         if limit and limit < len(lines):
#             lines = lines[:limit] + [f"... {len(lines) - limit} more lines."]
#         return "\n".join(lines)

# class WriteFileTool(BaseTool):
#     """ 
#     Tool that let agent write files inside the workspace.

#     The model privided:
#         {"path": "string", "text": "string"}

#     The runtime calls this through BaseTool.call(), so
    
    

#     """



def safe_path(workdir: Path, p: str) -> Path:
    """
    Turn an untrusted model-provided path into a workspace-scoped Path.

    File Tools recieve paths from the model. Those paths are not trusted:
    they may be absolute paths or contain '..' segments that escape the
    project directory.

    This function is the filesystem boundary for local tools. It resolves
    the path against workdir and reject anything outside workdir

    Every file tool should use this before reading, writing, or editinf files.
    """
    path = (workdir / p).resolve()
    if not path.is_relative_to(workdir):
        raise ValueError(f"path escape workspace: {path}")
    return path


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


    
# if __name__ == "__main__":
#     tool = BashTool(".")

#     print("=== schema ===")
#     print(tool.to_anthropic_tool())

#     print("=== valid command ===")
#     print(tool.call({"command": "pwd"}))

#     print("=== invalid input ===")
#     print(tool.call({"cmd": "pwd"}))

#     print("=== dangerous command ===")
#     print(tool.call({"command": "sudo ls"}))                             

class BaseTool:
    """
    It is a base tool.

    fix the agent's tool_call lifecircle

    model-input depended by identity tool.

    runtime config include workdir and timeout

    boundary all tools must work in workspace

    BaseTool.call() can be call by any other tool.
    """


class ReadFileTool(BaseTool):
    """
    该工具名为read_file

    其给agent增加了读取文件内容的能力

    模型端调用形式为：
        name = "read_file"
        input = {"path": "abc.txt", "limit": 10}

    workdir为其runtime config
    
    调用其需确保模型端输入和runtime端config均合法
        name不为空且为str
        path不为空且为str
        limit可为空，若非空为int

    该工具会拒绝：
        workspace外的路径
        不存在的路径
        不是文件的路径
            
    agent_loop可通过BaseTool.call()调用该工具
    """
    def __init__(self, workdir):
        """
        接收runtime config workdir，并将其作为文件读取的workspace边界
        """
        self.workdir = Path(workdir).resolve()
    
    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        """
        模型端输入格式的合法性，确保args.get("path")非空且为str
        args.get("limit")在非空时为integer
        """
        args = super().validate(args)

        path = args.get("path")
        limit = args.get("limit")
        if not path or not isinstance(path, str):
            raise ValueError("path must be non-empty and type is string")
        if limit and isinstance(limit, int):
            raise ValueError("limit must be integer.")

        return {
            "path": path,
            "limit": limit,
        }

    def check_permission(self, args) -> tuple[bool, str]:
        """
        工具权限的合法性：
            path是否存在
            path是否为文件
            work/path有没有逃逸workdir
        """
        try:
            path = safe_path(self.workdir, args["path"])
        except Exception as e:
            return False, f"Error: {e}"    
        
        if not path.exists():
            return False, f"File not found: {path}"
        
        if not path.is_file():
            return False,f"It is not a file: {path}"
        
        return True, ""

    def run(self, args: dict[str, Any]) -> str: 
        """
        具体工具的执行步骤，读取limit行内容，返回为str
        """ 
        f = safe_path(self.workdir, args["path"])
        limit = args.get("limit")
        lines = f.read_text().splitlines()
        if not limit and limit < len(lines):
            lines = lines[:limit] + [f"... {len(lines) - limit} more lines"]
        return "\n".join(lines)
    
class WriteFileTool(BaseTool):
    """
    名为write_file的一个工具

    该工具是的agent具备在文件中写入内容的能力

    模型端的调用形式为：
        name = "write_file"
        input = {""}
    """

    def __init__(self, workdir):
        """
        """

    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        """
        """

    def check_permission(self, args: dict[str, Any]) -> tuple[bool, str]:
        """
        """

    def run(self, args: dict[str, Any]) -> str:
        """
        """

class EditFileTool(BaseTool):
    """

    """

    def __init__(self, workdir):
        """
        """

    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        """
        """

    def check_permission(self, args: dict[str, Any]) -> tuple[bool, str]:
        """
        """

    def run(self, args: dict[str, Any]) -> str:
        """
        """