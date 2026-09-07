from unittest import TestCase

from core.memory.bge_reranker import (
    DEFAULT_BGE_RERANKER_MODEL,
    BGEReranker,
)
from core.memory.vector_store import MemorySearchResult


class BGERerankerTests(TestCase):
    def test_strict_cuda_requires_cuda_zero_and_fp16(self):
        with self.assertRaisesRegex(ValueError, "cuda:0"):
            BGEReranker(require_cuda=True, use_fp16=True, device="cuda:1")
        with self.assertRaisesRegex(ValueError, "FP16"):
            BGEReranker(require_cuda=True, use_fp16=False, device="cuda:0")

    def test_rejects_invalid_inference_sizes(self):
        with self.assertRaisesRegex(ValueError, "batch_size"):
            BGEReranker(batch_size=0)
        with self.assertRaisesRegex(ValueError, "max_length"):
            BGEReranker(max_length=0)

    def test_lazily_loads_once_and_maps_scores_back_to_ranked_results(self):
        factory_calls = []

        class FakeModel:
            calls = []

            def compute_score(self, sentence_pairs, *, normalize):
                self.calls.append((sentence_pairs, normalize))
                return [0.1, 0.9, 0.4]

        model = FakeModel()

        def build_model(model_name):
            factory_calls.append(model_name)
            return model

        candidates = [
            MemorySearchResult(
                id=str(index),
                data=text,
                scope="user",
                score=0.0,
                metadata={},
            )
            for index, text in enumerate(("first", "second", "third"))
        ]
        reranker = BGEReranker(model_factory=build_model)

        self.assertEqual(factory_calls, [])

        first_results = reranker.rerank(
            query="query",
            candidates=candidates,
            limit=2,
        )
        reranker.rerank(query="another query", candidates=candidates, limit=1)

        self.assertEqual(factory_calls, [DEFAULT_BGE_RERANKER_MODEL])
        self.assertEqual(
            model.calls[0],
            (
                [
                    ["query", "first"],
                    ["query", "second"],
                    ["query", "third"],
                ],
                True,
            ),
        )
        self.assertEqual(
            [(result.id, result.score) for result in first_results],
            [("1", 0.9), ("2", 0.4)],
        )
