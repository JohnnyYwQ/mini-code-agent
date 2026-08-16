from dataclasses import replace
from unittest import TestCase

from evals.memory_retrieval.rerank_stage import (
    RERANKING_NAME,
    _memory_texts_by_case,
    _rerank_record,
)


class ReversingReranker:
    def rerank(self, *, query, candidates, limit):
        return [
            replace(candidate, score=float(index))
            for index, candidate in enumerate(reversed(candidates), start=1)
        ][:limit]


class RerankStageTests(TestCase):
    def test_builds_case_local_session_text_lookup(self):
        dataset = {
            "queries": [{"id": "q1", "context": {"space_id": "space:q1"}}],
            "memories": [
                {
                    "space_id": "space:q1",
                    "source_session_id": "s1",
                    "text": "session one",
                }
            ],
        }

        self.assertEqual(
            _memory_texts_by_case(dataset),
            {"q1": {"s1": "session one"}},
        )

    def test_reranks_only_the_frozen_rrf_candidates(self):
        candidate_record = {
            "schema": 1,
            "case_id": "q1",
            "question_type": "single-session-user",
            "query": "question",
            "relevant_ids": ["s2"],
            "corpus_ids": ["s1", "s2", "s3"],
            "rankings": {
                "e5": [],
                "bm25": [],
                "rrf": [
                    {"id": "s1", "score": 0.3},
                    {"id": "s2", "score": 0.2},
                ],
            },
        }

        result = _rerank_record(
            candidate_record=candidate_record,
            memory_text_by_session={"s1": "one", "s2": "two", "s3": "three"},
            reranker=ReversingReranker(),
        )

        self.assertEqual(
            [item["id"] for item in result["rankings"][RERANKING_NAME]],
            ["s2", "s1"],
        )
        self.assertNotIn("s3", result["rankings"][RERANKING_NAME])
