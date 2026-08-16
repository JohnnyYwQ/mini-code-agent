from unittest import TestCase

from evals.memory_retrieval.candidate_stage import (
    _has_verified_e5_cuda_execution,
    _rank_items,
    reciprocal_rank_fusion,
)


class CandidateStageTests(TestCase):
    def test_accepts_profiled_cuda_compute_with_cpu_shape_support(self):
        self.assertTrue(
            _has_verified_e5_cuda_execution(
                {
                    "device_id": 0,
                    "providers": [
                        "CUDAExecutionProvider",
                        "CPUExecutionProvider",
                    ],
                    "cuda_compute_ops": ["Attention", "MatMul"],
                    "cpu_compute_ops": [],
                    "cpu_profiled_ops": ["Shape"],
                }
            )
        )

    def test_rejects_profiled_cpu_compute(self):
        self.assertFalse(
            _has_verified_e5_cuda_execution(
                {
                    "device_id": 0,
                    "providers": [
                        "CUDAExecutionProvider",
                        "CPUExecutionProvider",
                    ],
                    "cuda_compute_ops": ["Attention"],
                    "cpu_compute_ops": ["MatMul"],
                }
            )
        )

    def test_ranking_uses_corpus_order_to_break_score_ties(self):
        ranking = _rank_items(
            point_scores={"s1": 0.5, "s2": 0.5, "s3": 0.9},
            corpus_ids=["s1", "s2", "s3"],
            missing_score=0.0,
            limit=3,
        )

        self.assertEqual([item["id"] for item in ranking], ["s3", "s1", "s2"])

    def test_ranking_rejects_non_finite_scores(self):
        with self.assertRaisesRegex(RuntimeError, "finite"):
            _rank_items(
                point_scores={"s1": float("inf")},
                corpus_ids=["s1"],
                missing_score=0.0,
                limit=1,
            )

    def test_rrf_combines_rankings_and_uses_first_seen_for_ties(self):
        ranking = reciprocal_rank_fusion(
            [{"id": "a"}, {"id": "b"}],
            [{"id": "b"}, {"id": "a"}],
            limit=2,
            rank_constant=60,
        )

        self.assertEqual([item["id"] for item in ranking], ["a", "b"])
        self.assertAlmostEqual(ranking[0]["score"], 1 / 61 + 1 / 62)
