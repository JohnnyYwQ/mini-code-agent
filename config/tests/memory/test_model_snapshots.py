from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from evals.memory_retrieval.model_snapshots import ModelSnapshot, resolve_snapshot


class ModelSnapshotTests(TestCase):
    def setUp(self):
        self.snapshot = ModelSnapshot(
            repo_id="example/model",
            revision="a" * 40,
            required_patterns=("config.json", "weights/*.onnx"),
            allow_patterns=("config.json", "weights/*.onnx"),
        )

    def _write_complete_snapshot(self, cache_dir: Path) -> Path:
        snapshot_path = self.snapshot.expected_path(cache_dir)
        (snapshot_path / "weights").mkdir(parents=True)
        (snapshot_path / "config.json").write_text("{}", encoding="utf-8")
        (snapshot_path / "weights" / "model.onnx").write_bytes(b"onnx")
        return snapshot_path

    @patch("evals.memory_retrieval.model_snapshots.snapshot_download")
    def test_reuses_complete_exact_snapshot_without_hub_call(self, snapshot_download):
        with TemporaryDirectory() as temporary_dir:
            cache_dir = Path(temporary_dir)
            expected_path = self._write_complete_snapshot(cache_dir)

            resolved = resolve_snapshot(
                self.snapshot,
                cache_dir=cache_dir,
                local_files_only=True,
            )

        self.assertEqual(resolved, expected_path)
        snapshot_download.assert_not_called()

    @patch("evals.memory_retrieval.model_snapshots.snapshot_download")
    def test_downloads_only_the_pinned_revision_when_cache_is_incomplete(
        self,
        snapshot_download,
    ):
        with TemporaryDirectory() as temporary_dir:
            cache_dir = Path(temporary_dir)
            expected_path = self._write_complete_snapshot(cache_dir)
            (expected_path / "config.json").unlink()

            def complete_download(**_):
                (expected_path / "config.json").write_text("{}", encoding="utf-8")
                return str(expected_path)

            snapshot_download.side_effect = complete_download
            resolved = resolve_snapshot(
                self.snapshot,
                cache_dir=cache_dir,
                local_files_only=False,
            )

        self.assertEqual(resolved, expected_path)
        snapshot_download.assert_called_once_with(
            repo_id="example/model",
            revision="a" * 40,
            cache_dir=str(cache_dir),
            allow_patterns=("config.json", "weights/*.onnx"),
            local_files_only=False,
        )

    def test_rejects_incomplete_snapshot(self):
        with TemporaryDirectory() as temporary_dir:
            snapshot_path = Path(temporary_dir)
            (snapshot_path / "config.json").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "weights/\\*.onnx"):
                self.snapshot.validate(snapshot_path)
