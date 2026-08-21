import re
from pathlib import Path
from unittest import TestCase

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_DOCUMENTATION = (
    Path("README.md"),
    Path("README.en.md"),
    Path("docs/architecture.md"),
    Path("docs/architecture.en.md"),
)
MARKDOWN_LINK = re.compile(r"!?\[[^]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+", re.MULTILINE)


class PublicDocumentationJourneyTests(TestCase):
    def test_root_readmes_reach_matching_bilingual_architecture_guides(self):
        chinese_readme = (REPOSITORY_ROOT / "README.md").read_text()
        english_readme = (REPOSITORY_ROOT / "README.en.md").read_text()

        self.assertIn("(docs/architecture.md)", chinese_readme)
        self.assertIn("(docs/architecture.en.md)", english_readme)

        chinese_guide = (REPOSITORY_ROOT / "docs/architecture.md").read_text()
        english_guide = (REPOSITORY_ROOT / "docs/architecture.en.md").read_text()
        self.assertIn("(architecture.en.md)", chinese_guide)
        self.assertIn("(architecture.md)", english_guide)

        chinese_hierarchy = MARKDOWN_HEADING.findall(chinese_guide)
        english_hierarchy = MARKDOWN_HEADING.findall(english_guide)
        self.assertEqual(chinese_hierarchy, english_hierarchy)

    def test_public_documentation_local_links_resolve(self):
        for document in PUBLIC_DOCUMENTATION:
            document_path = REPOSITORY_ROOT / document
            text = document_path.read_text()
            for raw_target in MARKDOWN_LINK.findall(text):
                target = raw_target.split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                with self.subTest(document=str(document), target=target):
                    self.assertTrue((document_path.parent / target).exists())
