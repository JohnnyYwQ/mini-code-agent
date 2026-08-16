from pathlib import Path
from unittest import TestCase

from core.memory.flashrank_reranker import (
    DEFAULT_FLASHRANK_MODEL,
    FlashRankReranker,
)
from core.memory.vector_store import MemorySearchResult


class FlashRankRerankerTests(TestCase):
    def test_lazily_loads_once_and_maps_ranked_results(self):
        factory_calls = []
        backend_calls = []

        def backend(*, query, passages):
            backend_calls.append((query, passages))
            return [
                {**passages[1], "score": 0.9},
                {**passages[2], "score": 0.4},
                {**passages[0], "score": 0.1},
            ]

        def build_backend(model_name, cache_dir):
            factory_calls.append((model_name, cache_dir))
            return backend

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
        cache_dir = Path("test-cache")
        reranker = FlashRankReranker(
            cache_dir=cache_dir,
            backend_factory=build_backend,
        )

        self.assertEqual(factory_calls, [])

        first_results = reranker.rerank(
            query="query",
            candidates=candidates,
            limit=2,
        )
        reranker.rerank(query="another query", candidates=candidates, limit=1)

        self.assertEqual(factory_calls, [(DEFAULT_FLASHRANK_MODEL, cache_dir)])
        self.assertEqual(
            backend_calls[0],
            (
                "query",
                [
                    {"id": 0, "text": "first"},
                    {"id": 1, "text": "second"},
                    {"id": 2, "text": "third"},
                ],
            ),
        )
        self.assertEqual(
            [(result.id, result.score) for result in first_results],
            [("1", 0.9), ("2", 0.4)],
        )
