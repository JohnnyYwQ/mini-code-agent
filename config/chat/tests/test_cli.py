from unittest import TestCase

from core.agent import CLI_PROMPT
from prompt_toolkit.formatted_text import to_formatted_text


class CliPromptTests(TestCase):
    def test_parses_ansi_escape_sequences_as_style(self):
        fragments = to_formatted_text(CLI_PROMPT)

        self.assertFalse(any("\033" in text for _, text in fragments))
        self.assertTrue(any(style for style, _ in fragments))
