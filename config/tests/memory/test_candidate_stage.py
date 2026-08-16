from unittest import TestCase

from evals.memory_retrieval.candidate_stage import (
    _has_verified_e5_cuda_execution,
    _rank_items,
    _retrieve_case,
    reciprocal_rank_fusion,
)
from qdrant_client import models


class StaticDenseEncoder:
    def encode_documents(self, texts, *, batch_size):
        return [[1.0] + [0.0] * 767 for _ in texts]

    def encode_query(self, text):
        return [1.0] + [0.0] * 767


class StaticBM25Encoder:
    def encode_documents(self, texts, *, batch_size):
        return [
            models.SparseVector(indices=[1], values=[float(index)])
            for index, _ in enumerate(texts, start=1)
        ]

    def encode_query(self, text):
        return models.SparseVector(indices=[1], values=[1.0])


class CandidateStageTests(TestCase):
    def test_preserves_duplicate_source_session_occurrences(self):
        memory_ids = [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
            "00000000-0000-0000-0000-000000000003",
        ]
        record = _retrieve_case(
            dense_encoder=StaticDenseEncoder(),
            bm25_encoder=StaticBM25Encoder(),
            case={
                "id": "duplicate-session-label",
                "query": "question",
                "relevant_session_ids": ["target"],
                "tags": ["longmemeval", "single-session-user", "single"],
            },
            corpus=[
                {
                    "id": memory_ids[0],
                    "source_session_id": "duplicate",
                    "text": "same distractor",
                },
                {
                    "id": memory_ids[1],
                    "source_session_id": "target",
                    "text": "target evidence",
                },
                {
                    "id": memory_ids[2],
                    "source_session_id": "duplicate",
                    "text": "same distractor",
                },
            ],
            candidate_count=3,
            e5_batch_size=2,
        )

        self.assertEqual(
            record["corpus_ids"],
            ["duplicate", "target", "duplicate"],
        )
        self.assertEqual(record["corpus_memory_ids"], memory_ids)
        for ranking_name in ("e5", "bm25", "rrf"):
            ranking = record["rankings"][ranking_name]
            self.assertEqual(len(ranking), 3)
            self.assertEqual(
                {item["memory_id"] for item in ranking},
                set(memory_ids),
            )
            self.assertEqual(
                sorted(item["id"] for item in ranking),
                ["duplicate", "duplicate", "target"],
            )

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
