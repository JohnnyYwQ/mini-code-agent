from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from core.skills import SkillManager


class SkillManagerTests(TestCase):
    def test_discovers_skill_and_preserves_instruction_body(self):
        """
        normally register, list, load skill and no change to content for normal yaml format skill
        """
        with TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / "reviewer"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: reviewer\n"
                "description: Review code safely\n"
                "---\n"
                "    Keep this indentation.\n"
            )

            manager = SkillManager(temp_dir)

        self.assertEqual(
            manager.list_skills(),
            [{"name": "reviewer", "description": "Review code safely"}],
        )
        self.assertEqual(
            manager.load_skill("reviewer"),
            "    Keep this indentation.\n",
        )

    def test_uses_directory_name_and_body_heading_as_defaults(self):
        """
        can extract metadata from none-yaml format text
        """
        with TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / "code-review"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "# Code Review\nReview the requested changes.\n"
            )

            manager = SkillManager(temp_dir)

        self.assertEqual(
            manager.list_skills(),
            [{"name": "code-review", "description": "Code Review"}],
        )
        self.assertEqual(
            manager.load_skill("code-review"),
            "# Code Review\nReview the requested changes.\n",
        )

    def test_ignores_entries_that_are_not_valid_skills(self):
        """
        only txt, empty dir, empty SKILL.md all cant normally register
        """
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "ordinary-file.txt").write_text("not a skill")
            (root / "missing-manifest").mkdir()

            empty_skill = root / "empty-skill"
            empty_skill.mkdir()
            (empty_skill / "SKILL.md").write_text("")

            invalid_metadata = root / "invalid-metadata"
            invalid_metadata.mkdir()
            (invalid_metadata / "SKILL.md").write_text(
                "---\n"
                "name:\n"
                "  - invalid\n"
                "description: Invalid name type\n"
                "---\n"
                "# Instructions\n"
            )

            manager = SkillManager(root)

        self.assertEqual(manager.list_skills(), [])

    def test_missing_skills_directory_produces_empty_registry(self):
        """
        missing skills_dir will not register or load any skill
        """
        with TemporaryDirectory() as temp_dir:
            manager = SkillManager(Path(temp_dir) / "missing")

        self.assertEqual(manager.list_skills(), [])

    def test_load_skill_reports_unknown_name(self):
        """
        load unknown skill will return correct info
        """
        with TemporaryDirectory() as temp_dir:
            manager = SkillManager(temp_dir)

        self.assertEqual(
            manager.load_skill("missing"),
            "skill missing not found in registry.",
        )
