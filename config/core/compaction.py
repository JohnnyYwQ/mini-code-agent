"""Conversation-history compaction.

The agent loop owns the Anthropic message protocol. This module only owns
snapshotting and reducing an already-built message history.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CompactionConfig:
    persist_threshold: int = 4_000
    keep_recent: int = 8
    context_limit: int = 20_000
    max_tool_result_chars: int = 12_000
    max_messages: int = 100


DEFAULT_COMPACTION_CONFIG = CompactionConfig()


def _block_type(block: object) -> object:
    if isinstance(block, dict):
        return block.get("type")
    return getattr(block, "type", None)


class ContextCompactor:
    """Persist and compact conversation history before model calls."""

    def __init__(
        self,
        transcript_dir: str | Path,
        tool_results_dir: str | Path,
        summarize: Callable[[str], str],
        *,
        config: CompactionConfig = DEFAULT_COMPACTION_CONFIG,
    ):
        self.transcript_dir = Path(transcript_dir)
        self.tool_results_dir = Path(tool_results_dir)
        self.summarize = summarize
        self.config = config

    def prepare_for_model(self, messages: list[dict]) -> list[dict]:
        """Snapshot and compact messages before a normal model request."""
        self._write_transcript(messages)
        messages = self._tool_result_budget(messages)
        messages = self._snip_compact(messages)
        messages = self._micro_compact(messages)
        if self._estimate_tokens(messages) > self.config.context_limit:
            return self.compact_history(messages)
        return messages

    def compact_history(self, messages: list[dict]) -> list[dict]:
        """Replace the supplied closed history with one user summary."""
        summary = self._summary_history(messages)
        return [{"role": "user", "content": f"[Compacted]\n\n{summary}"}]

    @staticmethod
    def _estimate_tokens(messages: list[dict]) -> int:
        return len(str(messages)) // 4

    @staticmethod
    def _collect_tool_results(messages: list[dict]) -> list[tuple[int, int, dict]]:
        tool_results = []
        for message_index, message in enumerate(messages):
            if message.get("role") != "user":
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block_index, block in enumerate(content):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_results.append((message_index, block_index, block))
        return tool_results

    def _micro_compact(self, messages: list[dict]) -> list[dict]:
        results = self._collect_tool_results(messages)
        if len(results) <= self.config.keep_recent:
            return messages
        for _, _, block in results[: -self.config.keep_recent]:
            if len(block.get("content", "")) > 120:
                block["content"] = "[Earlier tool result compacted, rerun if needed]"
        return messages

    def _tool_result_budget(self, messages: list[dict]) -> list[dict]:
        last_message = messages[-1] if messages else None
        if (
            not last_message
            or last_message.get("role") != "user"
            or not isinstance(last_message.get("content"), list)
        ):
            return messages

        blocks = [
            block
            for block in last_message["content"]
            if isinstance(block, dict) and block.get("type") == "tool_result"
        ]
        total = sum(len(str(block.get("content", ""))) for block in blocks)
        if total <= self.config.max_tool_result_chars:
            return messages

        ranked = sorted(
            blocks,
            key=lambda block: len(str(block.get("content", ""))),
            reverse=True,
        )
        for block in ranked:
            if total <= self.config.max_tool_result_chars:
                break

            tool_use_id = str(block.get("tool_use_id")) or "unknown"
            content = block.get("content")
            output = "" if content is None else str(content)

            block["content"] = self._persist_large_output(tool_use_id, output)
            total = sum(len(str(item.get("content", ""))) for item in blocks)
        return messages

    def _persist_large_output(self, tool_use_id: str, output: str) -> str:
        if len(output) <= self.config.persist_threshold:
            return output
        self.tool_results_dir.mkdir(parents=True, exist_ok=True)
        path = self.tool_results_dir / f"tool_result_{tool_use_id}"
        if not path.exists():
            path.write_text(output)
        return (
            "<persist large output>\n"
            f"Full output:{path}\n"
            f"Preview:\n{output[:2000]}\n"
            "</persist large output>"
        )

    def _snip_compact(self, messages: list[dict]) -> list[dict]:
        if len(messages) <= self.config.max_messages:
            return messages

        keep_head = 3
        keep_tail = self.config.max_messages - 3 - 1
        head_boundary = messages[keep_head - 1]
        tail_boundary = messages[-keep_tail]

        if not self._can_snip(head_boundary):
            if head_boundary.get("role") == "assistant":
                keep_head += 1
        if not self._can_snip(tail_boundary):
            if tail_boundary.get("role") == "user":
                keep_tail += 1

        snipped = len(messages) - keep_head - keep_tail
        if snipped <= 0:
            return messages
        return (
            messages[:keep_head]
            + [{"role": "user", "content": f"snipped {snipped} messages"}]
            + messages[-keep_tail:]
        )

    @staticmethod
    def _can_snip(message: dict) -> bool:
        if message.get("role") == "assistant":
            for block in message.get("content", []):
                if _block_type(block) == "tool_use":
                    return False
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if _block_type(block) == "tool_result":
                        return False
        return True

    def _write_transcript(self, messages: list[dict]) -> Path:
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
        path = self.transcript_dir / f"transcription_{time.time_ns()}.jsonl"
        with path.open("w") as file:
            for message in messages:
                file.write(json.dumps(message, default=str) + "\n")
        return path

    def _summary_history(self, messages: list[dict]) -> str:
        conversation = json.dumps(messages, default=str)[:80000]
        prompt = (
            "Summarize this coding-agent conversation so work can continue.\n"
            "Preserve: 1. current goal, 2. key findings/decisions, "
            "3. file read/changed, 4. remaining work, 5. user constrains\n"
            "Be compact but concret" + conversation
        )
        return self.summarize(prompt)
