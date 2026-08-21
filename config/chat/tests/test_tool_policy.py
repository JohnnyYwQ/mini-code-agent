from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase

from core.agent_runtime import AgentRuntime, AgentRuntimeConfig
from core.tooling import TOOLS


class ToolSchemaTests(TestCase):
    def test_read_file_limit_is_a_non_negative_integer(self):
        read_file = next(tool for tool in TOOLS if tool["name"] == "read_file")

        self.assertEqual(
            read_file["input_schema"]["properties"]["limit"],
            {"type": "integer", "minimum": 0},
        )

    def test_every_tool_has_a_complete_definition(self):
        for tool in TOOLS:
            with self.subTest(tool=tool.get("name")):
                self.assertIsInstance(tool["name"], str)
                self.assertIsInstance(tool["description"], str)
                self.assertEqual(tool["input_schema"]["type"], "object")

    def test_regular_tool_definitions_and_handlers_stay_in_sync(self):
        defined = {tool["name"] for tool in TOOLS}

        with TemporaryDirectory() as temp_dir:
            runtime = AgentRuntime(
                workspace_path=Path(temp_dir),
                config=AgentRuntimeConfig(model="test-model", api_key="test-key"),
                message_client=SimpleNamespace(),
            )

        self.assertEqual(
            set(runtime.tool_handlers),
            defined - {"compact"},
        )
