import json
import tempfile
from pathlib import Path
from unittest import TestCase

from evals.memory_retrieval.artifact_io import (
    atomic_write_json,
    canonical_digest,
    read_resumable_jsonl,
)


class EvaluationArtifactIOTests(TestCase):
    def test_canonical_digest_ignores_mapping_order(self):
        self.assertEqual(
            canonical_digest({"b": 2, "a": 1}),
            canonical_digest({"a": 1, "b": 2}),
        )

    def test_rejects_non_finite_json_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"

            with self.assertRaises(ValueError):
                atomic_write_json(path, {"score": float("nan")})

    def test_discards_only_a_truncated_final_jsonl_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.jsonl"
            path.write_text(
                '{"case_id":"one","value":1}\n{"case_id":"two"',
                encoding="utf-8",
            )

            records = read_resumable_jsonl(path)

            self.assertEqual(records, {"one": {"case_id": "one", "value": 1}})
            self.assertEqual(
                [json.loads(line) for line in path.read_text().splitlines()],
                [{"case_id": "one", "value": 1}],
            )
