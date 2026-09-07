from unittest import TestCase

from core.frontmatter import parse_frontmatter


class ParseFrontmatterTests(TestCase):
    def test_parses_yaml_mapping_and_preserves_body(self):
        text = (
            "---\n"
            "name: reviewer\n"
            'description: "Checks code: safely"\n'
            "enabled: true\n"
            "tags:\n"
            "  - python\n"
            "  - django\n"
            "---\n"
            "# Instructions\n"
        )

        metadata, body = parse_frontmatter(text)

        self.assertEqual(
            metadata,
            {
                "name": "reviewer",
                "description": "Checks code: safely",
                "enabled": True,
                "tags": ["python", "django"],
            },
        )
        self.assertEqual(body, "# Instructions\n")

    def test_returns_original_text_without_complete_frontmatter(self):
        cases = [
            "# Instructions\n",
            "---\nname: reviewer\n# Instructions\n",
            "---invalid\nname: reviewer\n---\nbody\n",
            "---\nname: reviewer\n---invalid\nbody\n",
        ]

        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(parse_frontmatter(text), ({}, text))

    def test_empty_invalid_or_non_mapping_yaml_returns_empty_metadata(self):
        cases = [
            ("", "body\n"),
            ("name: [invalid\n", "body\n"),
            ("- python\n- django\n", "body\n"),
            ("plain string\n", "body\n"),
        ]

        for yaml_text, expected_body in cases:
            with self.subTest(yaml_text=yaml_text):
                text = f"---\n{yaml_text}---\n{expected_body}"
                self.assertEqual(
                    parse_frontmatter(text),
                    ({}, expected_body),
                )

    def test_supports_crlf_and_preserves_line_endings(self):
        text = "---\r\nname: reviewer\r\n---\r\nbody\r\n"

        metadata, body = parse_frontmatter(text)

        self.assertEqual(metadata, {"name": "reviewer"})
        self.assertEqual(body, "body\r\n")

    def test_closing_delimiter_can_be_at_end_of_file(self):
        text = "---\nname: reviewer\n---"

        metadata, body = parse_frontmatter(text)

        self.assertEqual(metadata, {"name": "reviewer"})
        self.assertEqual(body, "")
