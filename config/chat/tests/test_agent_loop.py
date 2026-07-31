import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("MODEL_ID", "test-model")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-api-key")

from core.agent import agent_loop, validate_anthropic_config
from core.compaction import ContextCompactor
from core.todo import TodoManager


class AgentLoopIntegrationTests(TestCase):
    def test_model_requested_compaction_preserves_tool_protocol(self):
        prompts = []
        compact_block = SimpleNamespace(
            type="tool_use",
            name="compact",
            input={},
            id="compact-1",
        )
        responses = [
            SimpleNamespace(stop_reason="tool_use", content=[compact_block]),
            SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="done")],
            ),
        ]
        messages = [{"role": "user", "content": "old history"}]

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compactor = ContextCompactor(
                transcript_dir=root / "transcripts",
                tool_results_dir=root / "tool-results",
                summarize=lambda prompt: prompts.append(prompt) or "summary",
                context_limit=100_000,
            )
            with (
                patch("core.agent.CONTEXT_COMPACTOR", compactor),
                patch("core.agent.MODEL", "test-model"),
                patch("core.agent.API_KEY", "test-api-key"),
                patch("core.agent.BASE_URL", None),
                patch(
                    "core.agent.client.messages.create",
                    side_effect=responses,
                ) as create,
            ):
                agent_loop(messages)
            transcript_count = len(list((root / "transcripts").glob("*.jsonl")))

        self.assertEqual(create.call_count, 2)
        self.assertEqual(transcript_count, 2)
        self.assertEqual(
            [message["role"] for message in messages],
            ["user", "assistant", "user", "assistant"],
        )
        self.assertEqual(
            messages[0],
            {"role": "user", "content": "[Compacted]\n\nsummary"},
        )
        self.assertEqual(messages[1]["content"], [compact_block])
        self.assertEqual(
            messages[2]["content"],
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "compact-1",
                    "content": (
                        "[Compacted]. Conversation history has been summaried."
                    ),
                }
            ],
        )
        self.assertIn("old history", prompts[0])

    def test_todo_tool_uses_extracted_manager(self):
        todo_block = SimpleNamespace(
            type="tool_use",
            name="todo",
            input={
                "items": [
                    {"id": 1, "text": "Ship changes", "state": "done"},
                ]
            },
            id="todo-1",
        )
        responses = [
            SimpleNamespace(stop_reason="tool_use", content=[todo_block]),
            SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="done")],
            ),
        ]
        messages = [{"role": "user", "content": "Track the work"}]

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compactor = ContextCompactor(
                transcript_dir=root / "transcripts",
                tool_results_dir=root / "tool-results",
                summarize=lambda prompt: "summary",
                context_limit=100_000,
            )
            with (
                patch("core.agent.CONTEXT_COMPACTOR", compactor),
                patch("core.agent.TODO", TodoManager()),
                patch("core.agent.MODEL", "test-model"),
                patch("core.agent.API_KEY", "test-api-key"),
                patch("core.agent.BASE_URL", None),
                patch(
                    "core.agent.client.messages.create",
                    side_effect=responses,
                ),
            ):
                agent_loop(messages)

        self.assertEqual(
            messages[2]["content"],
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "todo-1",
                    "content": "[x]: #1: Ship changes\n\n(1/1 completed)",
                }
            ],
        )

    def test_blocked_and_failed_tools_return_matching_results(self):
        blocked_bash = SimpleNamespace(
            type="tool_use",
            name="bash",
            input={"command": "sudo reboot"},
            id="bash-1",
        )
        missing_read = SimpleNamespace(
            type="tool_use",
            name="read_file",
            input={"path": "missing.txt"},
            id="read-1",
        )
        responses = [
            SimpleNamespace(
                stop_reason="tool_use",
                content=[blocked_bash, missing_read],
            ),
            SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="done")],
            ),
        ]
        messages = [{"role": "user", "content": "Use the tools"}]

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            compactor = ContextCompactor(
                transcript_dir=root / "transcripts",
                tool_results_dir=root / "tool-results",
                summarize=lambda prompt: "summary",
                context_limit=100_000,
            )
            with (
                patch("core.agent.WORKDIR", workspace),
                patch("core.agent.CONTEXT_COMPACTOR", compactor),
                patch("core.agent.MODEL", "test-model"),
                patch("core.agent.API_KEY", "test-api-key"),
                patch("core.agent.BASE_URL", None),
                patch(
                    "core.agent.client.messages.create",
                    side_effect=responses,
                ),
            ):
                agent_loop(messages)

        self.assertEqual(
            messages[2]["content"],
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "bash-1",
                    "content": "Permission denied by deny list",
                },
                {
                    "type": "tool_result",
                    "tool_use_id": "read-1",
                    "content": "Error: File not found missing.txt",
                },
            ],
        )

    @patch("core.agent.MAX_ROUNDS", 3)
    @patch("core.agent.client.messages.create")
    def test_agent_loop_raises_when_max_rounds_are_exceeded(
        self,
        create,
    ):
        tool_block = SimpleNamespace(
            type="tool_use",
            name="unknown tool",
            input={},
            id="toolu-test",
        )
        create.return_value = SimpleNamespace(
            stop_reason="tool_use",
            content=[tool_block],
        )
        messages = [{"role": "user", "content": "keep using tools"}]

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compactor = ContextCompactor(
                transcript_dir=root / "transcripts",
                tool_results_dir=root / "tool-results",
                summarize=lambda prompt: "summary",
                context_limit=100_000,
            )
            with patch("core.agent.CONTEXT_COMPACTOR", compactor):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "Agent exceeded max rounds",
                ):
                    agent_loop(messages)

        self.assertEqual(create.call_count, 3)


class AnthropicConfigTests(TestCase):
    @patch("core.agent.MODEL", "")
    def test_model_id_is_required(self):
        with self.assertRaisesRegex(RuntimeError, "MODEL_ID is required"):
            validate_anthropic_config()

    @patch("core.agent.MODEL", "test-model")
    @patch("core.agent.API_KEY", "")
    def test_api_key_is_required(self):
        with self.assertRaisesRegex(
            RuntimeError,
            "ANTHROPIC_API_KEY is required",
        ):
            validate_anthropic_config()

    @patch("core.agent.MODEL", "test-model")
    @patch("core.agent.API_KEY", "test-key")
    @patch("core.agent.BASE_URL", "test.test.test")
    def test_base_url_must_be_http_or_https(self):
        with self.assertRaisesRegex(
            RuntimeError,
            r"ANTHROPIC_BASE_URL must be a valid http\(s\) URL",
        ):
            validate_anthropic_config()

    @patch("core.agent.MODEL", "test-model")
    @patch("core.agent.API_KEY", "test-key")
    @patch("core.agent.BASE_URL", None)
    @patch(
        "core.agent.client.messages.create",
        side_effect=Exception("network down"),
    )
    def test_agent_loop_wraps_anthropic_request_error(self, create):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compactor = ContextCompactor(
                transcript_dir=root / "transcripts",
                tool_results_dir=root / "tool-results",
                summarize=lambda prompt: "summary",
                context_limit=100_000,
            )
            with patch("core.agent.CONTEXT_COMPACTOR", compactor):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "Anthropic API request failed",
                ):
                    agent_loop([{"role": "user", "content": "hello"}])

        create.assert_called_once()
