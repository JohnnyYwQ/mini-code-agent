from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from core.agent_runtime import AgentRuntime, AgentRuntimeConfig, build_memory_window
from core.compaction import CompactionConfig, ContextCompactor
from core.memory.memory import MemoryContext
from core.memory.vector_store import MemorySearchResult


class MemoryWindowTests(TestCase):
    def test_keeps_five_completed_turns_plus_visible_current_turn(self):
        messages = []
        for number in range(1, 7):
            messages.extend(
                [
                    {"role": "user", "content": f"question {number}"},
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": f"tool-{number}",
                                "name": "read_file",
                                "input": {"path": "README.md"},
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": f"tool-{number}",
                                "content": "tool output",
                            }
                        ],
                    },
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": f"answer {number}"}],
                    },
                ]
            )
        messages.extend(
            [
                {"role": "user", "content": "current question"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "current thought"},
                        {
                            "type": "tool_use",
                            "id": "remember-1",
                            "name": "remember",
                            "input": {},
                        },
                    ],
                },
            ]
        )

        window = build_memory_window(messages)

        self.assertEqual(
            window,
            [
                {"role": "user", "content": "question 2"},
                {"role": "assistant", "content": "answer 2"},
                {"role": "user", "content": "question 3"},
                {"role": "assistant", "content": "answer 3"},
                {"role": "user", "content": "question 4"},
                {"role": "assistant", "content": "answer 4"},
                {"role": "user", "content": "question 5"},
                {"role": "assistant", "content": "answer 5"},
                {"role": "user", "content": "question 6"},
                {"role": "assistant", "content": "answer 6"},
                {"role": "user", "content": "current question"},
                {"role": "assistant", "content": "current thought"},
            ],
        )


class AgentRuntimeMemoryTests(TestCase):
    def test_recalls_memory_and_exposes_no_argument_remember_tool(self):
        class FakeMemory:
            def __init__(self):
                self.added_messages = None
                self.added_context = None
                self.recall_rerank = None

            def recall(self, *, query, context, limit, rerank=False):
                self.recall_rerank = rerank
                return [
                    MemorySearchResult(
                        id="memory-1",
                        data="User prefers concise answers.",
                        scope="user",
                        score=1.0,
                        metadata={"user_id": context.user_id},
                    )
                ]

            def add(self, *, messages, context, prompt=None):
                self.added_messages = list(messages)
                self.added_context = context
                return ["new-memory"]

        remember_block = SimpleNamespace(
            type="tool_use",
            name="remember",
            input={},
            id="remember-1",
        )
        responses = [
            SimpleNamespace(
                stop_reason="tool_use",
                content=[
                    SimpleNamespace(type="text", text="I should remember this."),
                    remember_block,
                ],
            ),
            SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="Done.")],
            ),
        ]
        create = Mock(side_effect=responses)
        client = SimpleNamespace(messages=SimpleNamespace(create=create))
        memory = FakeMemory()
        context = MemoryContext(user_id="user-1", space_id="space-1")

        with TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            compactor = ContextCompactor(
                transcript_dir=workspace / "transcripts",
                tool_results_dir=workspace / "tool-results",
                summarize=lambda prompt: "summary",
                config=CompactionConfig(context_limit=100_000),
            )
            runtime = AgentRuntime(
                workspace_path=workspace,
                config=AgentRuntimeConfig(
                    model="test-model",
                    api_key="test-key",
                ),
                message_client=client,
                memory=memory,
                memory_context=context,
                compactor=compactor,
            )

            generated = runtime.run(
                messages=[
                    {
                        "role": "user",
                        "content": "Please keep answers concise.",
                    }
                ],
                latest_user_query="Please keep answers concise.",
            )

        first_request = create.call_args_list[0].kwargs
        self.assertIn("[user] User prefers concise answers.", first_request["system"])
        self.assertIs(memory.recall_rerank, True)
        remember_tool = next(
            tool for tool in first_request["tools"] if tool["name"] == "remember"
        )
        self.assertEqual(
            remember_tool["input_schema"],
            {"type": "object", "properties": {}},
        )
        self.assertEqual(
            memory.added_messages,
            [
                {"role": "user", "content": "Please keep answers concise."},
                {"role": "assistant", "content": "I should remember this."},
            ],
        )
        self.assertEqual(memory.added_context, context)
        self.assertEqual(
            [message["role"] for message in generated],
            ["assistant", "user", "assistant"],
        )
        self.assertEqual(
            generated[1]["content"][0]["content"],
            "Stored 1 Memory.",
        )

    def test_memory_failures_do_not_abort_the_agent_turn(self):
        class BrokenMemory:
            def recall(self, *, query, context, limit, rerank=False):
                return []

            def add(self, *, messages, context, prompt=None):
                try:
                    raise ValueError("invalid extraction target")
                except ValueError as error:
                    raise RuntimeError("remember failed") from error

        responses = [
            SimpleNamespace(
                stop_reason="tool_use",
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        name="remember",
                        input={},
                        id="remember-1",
                    )
                ],
            ),
            SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="Still completed.")],
            ),
        ]
        create = Mock(side_effect=responses)
        client = SimpleNamespace(messages=SimpleNamespace(create=create))

        with TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            runtime = AgentRuntime(
                workspace_path=workspace,
                config=AgentRuntimeConfig(
                    model="test-model",
                    api_key="test-key",
                ),
                message_client=client,
                memory=BrokenMemory(),
                memory_context=MemoryContext(user_id="user-1", space_id="space-1"),
                compactor=ContextCompactor(
                    transcript_dir=workspace / "transcripts",
                    tool_results_dir=workspace / "tool-results",
                    summarize=lambda prompt: "summary",
                    config=CompactionConfig(context_limit=100_000),
                ),
            )

            with self.assertLogs("core.agent_runtime", level="ERROR") as logs:
                generated = runtime.run(
                    messages=[{"role": "user", "content": "hello"}],
                    latest_user_query="hello",
                )

        self.assertNotIn(
            "<retrieved-memory>", create.call_args_list[0].kwargs["system"]
        )
        self.assertEqual(
            generated[1]["content"][0]["content"],
            "Error: RuntimeError: remember failed"
            " <- ValueError: invalid extraction target",
        )
        self.assertIn("Memory tool failed", logs.output[0])
        self.assertIn("ValueError: invalid extraction target", logs.output[0])
        self.assertIn("RuntimeError: remember failed", logs.output[0])
        self.assertEqual(
            generated[-1]["content"][0]["text"],
            "Still completed.",
        )
