from unittest import TestCase

from core.agent import CLI_PROMPT, visible_cli_history
from prompt_toolkit.formatted_text import to_formatted_text


class CliPromptTests(TestCase):
    def test_parses_ansi_escape_sequences_as_style(self):
        fragments = to_formatted_text(CLI_PROMPT)

        self.assertFalse(any("\033" in text for _, text in fragments))
        self.assertTrue(any(style for style, _ in fragments))


class CliHistoryTests(TestCase):
    def test_keeps_queries_and_final_assistant_replies_only(self):
        messages = [
            {"role": "user", "content": "Fix the bug."},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I will inspect it."},
                    {"type": "tool_use", "name": "read_file"},
                ],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "content": "file contents"}],
            },
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "done"},
                    {"type": "text", "text": "Fixed the overflow."},
                ],
            },
            {"role": "user", "content": "What changed?"},
            {"role": "assistant", "content": "The scoring function changed."},
        ]

        self.assertEqual(
            visible_cli_history(messages),
            [
                ("user", "Fix the bug."),
                ("assistant", "Fixed the overflow."),
                ("user", "What changed?"),
                ("assistant", "The scoring function changed."),
            ],
        )
