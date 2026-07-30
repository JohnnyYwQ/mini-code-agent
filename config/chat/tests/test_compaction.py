from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase

from core.compaction import ContextCompactor


def assistant_tool_use(tool_use_id: str) -> dict:
    return {
        "role": "assistant",
        "content": [
            SimpleNamespace(type="tool_use", id=tool_use_id),
        ],
    }


def user_tool_result(tool_use_id: str, content: str) -> dict:
    return {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": content,
            }
        ],
    }


def assistant_text(text: str) -> dict:
    return {
        "role": "assistant",
        "content": [SimpleNamespace(type="text", text=text)],
    }


class ContextCompactorTests(TestCase):
    def test_prepare_for_model_snapshots_before_compacting(self):
        """
        after transcript, existance of file and content of file 
        """
        old_output = "old output " * 20
        messages = [
            assistant_tool_use("old"),
            user_tool_result("old", old_output),
            assistant_tool_use("recent"),
            user_tool_result("recent", "recent output"),
        ]

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compactor = ContextCompactor(
                transcript_dir=root / "transcripts",
                tool_results_dir=root / "tool-results",
                summarize=lambda prompt: "summary",
                keep_recent=1,
                context_limit=100_000,
            )

            prepared = compactor.prepare_for_model(messages)
            transcripts = list((root / "transcripts").glob("*.jsonl"))

            self.assertEqual(len(transcripts), 1)
            self.assertIn(old_output, transcripts[0].read_text())

        self.assertEqual(
            prepared[1]["content"][0]["content"],
            "[Earlier tool result compacted, rerun if needed]",
        )
        self.assertEqual(
            prepared[3]["content"][0]["content"],
            "recent output",
        )

    def test_prepare_for_model_persists_large_latest_tool_result(self):
        """
        check if large tool result can be saved
        """
        large_output = "large output " * 30
        messages = [
            assistant_tool_use("large"),
            user_tool_result("large", large_output),
        ]

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tool_results_dir = root / "tool-results"
            compactor = ContextCompactor(
                transcript_dir=root / "transcripts",
                tool_results_dir=tool_results_dir,
                summarize=lambda prompt: "summary",
                persist_threshold=50,
                max_tool_result_chars=100,
                context_limit=100_000,
            )

            prepared = compactor.prepare_for_model(messages)

            persisted = tool_results_dir / "tool_result_large"
            self.assertEqual(persisted.read_text(), large_output)
            self.assertIn(
                f"Full output:{persisted}",
                prepared[1]["content"][0]["content"],
            )

    def test_prepare_for_model_summarizes_when_context_limit_is_exceeded(self):
        """
        测auto_compact是否正常触发
        """
        prompts = []

        def summarize(prompt):
            prompts.append(prompt)
            return "the summary"

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compactor = ContextCompactor(
                transcript_dir=root / "transcripts",
                tool_results_dir=root / "tool-results",
                summarize=summarize,
                context_limit=1,
            )

            prepared = compactor.prepare_for_model(
                [{"role": "user", "content": "a long conversation"}]
            )

        self.assertEqual(
            prepared,
            [{"role": "user", "content": "[Compacted]\n\nthe summary"}],
        )
        self.assertEqual(len(prompts), 1)
        self.assertIn("a long conversation", prompts[0])

    def test_compact_history_summarizes_only_the_supplied_closed_history(self):
        prompts = []

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compactor = ContextCompactor(
                transcript_dir=root / "transcripts",
                tool_results_dir=root / "tool-results",
                summarize=lambda prompt: prompts.append(prompt) or "summary",
            )
            messages = [
                {"role": "user", "content": "closed history"},
                assistant_tool_use("current-compact-call"),
            ]

            compacted = compactor.compact_history(messages[:-1])

            self.assertFalse((root / "transcripts").exists())

        self.assertEqual(
            compacted,
            [{"role": "user", "content": "[Compacted]\n\nsummary"}],
        )
        self.assertIn("closed history", prompts[0])
        self.assertNotIn("current-compact-call", prompts[0])

    def test_prepare_for_model_does_not_snip_between_tool_use_and_result(self):
        messages = [
            {"role": "user", "content": "first"},
            assistant_text("second"),
            assistant_tool_use("head-boundary"),
            user_tool_result("head-boundary", "head result"),
            {"role": "user", "content": "middle"},
            assistant_tool_use("tail-boundary"),
            user_tool_result("tail-boundary", "tail result"),
            assistant_text("last"),
        ]

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compactor = ContextCompactor(
                transcript_dir=root / "transcripts",
                tool_results_dir=root / "tool-results",
                summarize=lambda prompt: "summary",
                max_messages=6,
                context_limit=100_000,
            )

            prepared = compactor.prepare_for_model(messages)

        self.assertEqual(
            [block.id for message in prepared
             if message["role"] == "assistant"
             for block in message["content"]
             if block.type == "tool_use"],
            ["head-boundary", "tail-boundary"],
        )
        self.assertEqual(
            [block["tool_use_id"] for message in prepared
             if message["role"] == "user"
             and isinstance(message["content"], list)
             for block in message["content"]
             if block["type"] == "tool_result"],
            ["head-boundary", "tail-boundary"],
        )
        self.assertEqual(
            prepared[4],
            {"role": "user", "content": "snipped 1 messages"}
        )
        self.assertNotIn(
            {"role": "user", "content": "middle"},
            prepared
        )