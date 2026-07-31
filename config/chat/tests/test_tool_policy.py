import os
from unittest import TestCase

os.environ.setdefault("MODEL_ID", "test-model")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-api-key")

from core.agent import TOOL_HANDLERS, TOOLS


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

        self.assertEqual(
            set(TOOL_HANDLERS),
            defined - {"compact"},
        )
