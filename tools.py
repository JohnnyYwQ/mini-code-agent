import subprocess
from typing import Any

class Tool:
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
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
    
    def validate(self, args: dict[str, Any]) -> dict[str: Any]:
        if not isinstance(args, dict):
            raise ValueError("tool input must be an object")
        return args
    
    def check_permission(self, args: dict[str, Any]) -> tuple[bool, str]:
        return True, ""
    
    def run(self, args: dict[str, Any]) -> str:
        raise NotImplementedError

    def format_result(self, output: Any) -> str:
        return str(output)[:self.max_ouput_chars]
    
    def call(self, args: dict[str, Any]) -> str:
        try:
            args = self.validate(args)
            allowed, reason = self.check_permission(args)
            if not allowed:
                return f"Error: {reason}"
            
            output = self.run(args)
            return self.format_result(output)
        except Exception as e:
            return f"Error: {e}"