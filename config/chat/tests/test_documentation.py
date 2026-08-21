import re
from pathlib import Path
from unittest import TestCase

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_DOCUMENTATION = (
    Path("README.md"),
    Path("README.en.md"),
    Path("docs/architecture.md"),
    Path("docs/architecture.en.md"),
    Path("docs/memory-and-evaluation.md"),
    Path("docs/memory-and-evaluation.en.md"),
)
BILINGUAL_GUIDES = (
    (Path("docs/architecture.md"), Path("docs/architecture.en.md")),
    (
        Path("docs/memory-and-evaluation.md"),
        Path("docs/memory-and-evaluation.en.md"),
    ),
)
RETRIEVAL_EVIDENCE_FACTS = (
    "20260816-cu124-v1",
    "7b1f9466f3f334bc9f6b58225397c3daee55dbd5",
    "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442",
    "e267d5696e37a0c006d354c5b21ca5bb8f2620f9a48dbdf5a881f1d6b18b9a34",
    "92.60%",
    "94.74%",
    "97.61%",
    "95.69%",
)
MARKDOWN_LINK = re.compile(r"!?\[[^]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+", re.MULTILINE)
MARKDOWN_CODE_BLOCK = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


class PublicDocumentationJourneyTests(TestCase):
    def test_root_readmes_reach_matching_bilingual_guides(self):
        chinese_readme = (REPOSITORY_ROOT / "README.md").read_text()
        english_readme = (REPOSITORY_ROOT / "README.en.md").read_text()

        for chinese_path, english_path in BILINGUAL_GUIDES:
            with self.subTest(chinese=str(chinese_path), english=str(english_path)):
                self.assertIn(f"({chinese_path})", chinese_readme)
                self.assertIn(f"({english_path})", english_readme)

                chinese_guide = (REPOSITORY_ROOT / chinese_path).read_text()
                english_guide = (REPOSITORY_ROOT / english_path).read_text()
                self.assertIn(f"({english_path.name})", chinese_guide)
                self.assertIn(f"({chinese_path.name})", english_guide)
                self.assertEqual(
                    MARKDOWN_HEADING.findall(chinese_guide),
                    MARKDOWN_HEADING.findall(english_guide),
                )

    def test_bilingual_memory_evaluation_facts_and_commands_match(self):
        chinese_guide = (REPOSITORY_ROOT / BILINGUAL_GUIDES[1][0]).read_text()
        english_guide = (REPOSITORY_ROOT / BILINGUAL_GUIDES[1][1]).read_text()

        for fact in RETRIEVAL_EVIDENCE_FACTS:
            with self.subTest(fact=fact):
                self.assertIn(fact, chinese_guide)
                self.assertIn(fact, english_guide)
        self.assertEqual(
            MARKDOWN_CODE_BLOCK.findall(chinese_guide),
            MARKDOWN_CODE_BLOCK.findall(english_guide),
        )

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
