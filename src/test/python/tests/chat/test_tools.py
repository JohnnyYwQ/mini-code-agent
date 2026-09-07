import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("MODEL_ID", "test-model")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-api-key")

from core.tooling import (
    permission_hook,
    run_bash,
    run_edit,
    run_glob,
    run_read,
    run_write,
)


class FileToolTests(TestCase):
    def test_write_and_read_file_with_line_limits(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("core.tooling.WORKDIR", root):
                write_result = run_write(
                    "notes/session.txt",
                    "one\ntwo\nthree\n",
                )
                limited = run_read("notes/session.txt", limit=2)
                complete = run_read("notes/session.txt", limit=0)

        self.assertNotIn("Error:", write_result)
        self.assertEqual(limited, "one\ntwo\n... 1 more lines.")
        self.assertEqual(complete, "one\ntwo\nthree")

    def test_file_tools_reject_paths_outside_workspace(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside.txt"

            with patch("core.tooling.WORKDIR", workspace):
                write_result = run_write("../outside.txt", "blocked")
                with self.assertRaisesRegex(
                    ValueError,
                    "Path eacaped workspace",
                ):
                    run_read("../outside.txt")

            self.assertFalse(outside.exists())

        self.assertIn("Error: Path eacaped workspace", write_result)

    def test_edit_file_replaces_only_the_first_match(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("core.tooling.WORKDIR", root):
                run_write("sample.txt", "alpha beta alpha")

                edit_result = run_edit("sample.txt", "alpha", "omega")
                content = run_read("sample.txt", limit=0)

        self.assertNotIn("Error:", edit_result)
        self.assertEqual(content, "omega beta alpha")

    def test_edit_file_rejects_empty_old_text_without_changing_file(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("core.tooling.WORKDIR", root):
                run_write("sample.txt", "original")

                edit_result = run_edit("sample.txt", "", "prefix")
                content = run_read("sample.txt", limit=0)

        self.assertIn("old text can not be empty", edit_result)
        self.assertEqual(content, "original")

    def test_read_file_rejects_negative_limit(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("core.tooling.WORKDIR", root):
                run_write("sample.txt", "content")

                with self.assertRaisesRegex(
                    ValueError,
                    "limit must be non-negative",
                ):
                    run_read("sample.txt", limit=-1)

    def test_glob_finds_recursive_matches(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("core.tooling.WORKDIR", root):
                run_write("src/nested/module.py", "pass\n")
                run_write("src/nested/notes.txt", "notes\n")

                matches = run_glob("**/*.py")
                no_matches = run_glob("**/*.json")

        self.assertEqual(matches, "src/nested/module.py")
        self.assertEqual(no_matches, "(no matches)")

    def test_glob_does_not_return_matches_outside_workspace(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside.py"
            outside.write_text("pass\n")

            with patch("core.tooling.WORKDIR", workspace):
                matches = run_glob(str(outside))

        self.assertEqual(matches, "(no matches)")


class BashToolTests(TestCase):
    def test_bash_runs_in_workspace_and_returns_output(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("core.tooling.WORKDIR", root):
                working_directory = run_bash("pwd")
                output = run_bash("printf tool-output")

        self.assertEqual(Path(working_directory).resolve(), root.resolve())
        self.assertEqual(output, "tool-output")


class ToolPermissionTests(TestCase):
    def test_write_permission_allows_workspace_path_and_rejects_escape(self):
        with TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with patch("core.tooling.WORKDIR", workspace):
                allowed = permission_hook(
                    SimpleNamespace(
                        name="write_file",
                        input={"path": "inside.txt"},
                    )
                )
                denied = permission_hook(
                    SimpleNamespace(
                        name="write_file",
                        input={"path": "../outside.txt"},
                    )
                )

        self.assertIsNone(allowed)
        self.assertEqual(
            denied,
            "Permission denied: path outside workspace",
        )

    def test_bash_permission_blocks_deny_list_command(self):
        result = permission_hook(
            SimpleNamespace(
                name="bash",
                input={"command": "sudo reboot"},
            )
        )

        self.assertEqual(result, "Permission denied by deny list")

    def test_bash_permission_rejects_unapproved_destructive_command(self):
        block = SimpleNamespace(
            name="bash",
            input={"command": "rm generated.txt"},
        )

        with patch("builtins.input", return_value="n"):
            result = permission_hook(block)

        self.assertEqual(result, "Permission denied by user")
