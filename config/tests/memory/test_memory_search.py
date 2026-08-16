import uuid
from unittest import TestCase

from core.memory.memory import Memory, MemoryContext
from core.memory.qdrant_store import QdrantStore
from core.memory.vector_store import MemorySearchResult
from qdrant_client import QdrantClient, models


class FakeDenseEncoder:
    def encode_query(self, text):
        return [1.0, 0.0, 0.0]


class UnusedMemoryExtractor:
    def extract(self, *, messages, existing_memories, prompt=None):
        raise AssertionError("search must not extract new memories")


class FakeBM25Encoder:
    def encode_document(self, text):
        token = 10 if "ticket-4821" in text else 20
        return models.SparseVector(indices=[token], values=[1.0])

    def encode_query(self, text):
        return models.SparseVector(indices=[10], values=[1.0])


class MemorySearchTests(TestCase):
    def test_does_not_expose_caller_supplied_scope_filters(self):
        memory = Memory(
            extractor=UnusedMemoryExtractor(),
            dense_encoder=FakeDenseEncoder(),
            vector_store=object(),
        )

        self.assertFalse(hasattr(memory, "search"))

    def test_combines_dense_and_keyword_recall_within_user_scope(self):
        client = QdrantClient(":memory:")
        store = QdrantStore(
            client=client,
            collection_name="test_memory_search",
            dimension=3,
            bm25_encoder=FakeBM25Encoder(),
        )
        memory = Memory(
            extractor=UnusedMemoryExtractor(),
            dense_encoder=FakeDenseEncoder(),
            vector_store=store,
        )
        dense_memory_id = str(uuid.uuid4())
        second_dense_memory_id = str(uuid.uuid4())
        keyword_memory_id = str(uuid.uuid4())

        try:
            points = [
                (
                    dense_memory_id,
                    [1.0, 0.0, 0.0],
                    "用户偏好简洁回答",
                    "u1",
                ),
                (
                    second_dense_memory_id,
                    [0.9, 0.1, 0.0],
                    "用户喜欢结构化输出",
                    "u1",
                ),
                (
                    keyword_memory_id,
                    [0.0, 1.0, 0.0],
                    "支持工单编号 ticket-4821",
                    "u1",
                ),
                (
                    str(uuid.uuid4()),
                    [0.0, 1.0, 0.0],
                    "另一个用户的 ticket-4821",
                    "u2",
                ),
            ]
            for memory_id, vector, text, user_id in points:
                store.upsert(
                    memory_id=memory_id,
                    vector=vector,
                    payload={"data": text, "user_id": user_id},
                )

            results = memory.recall(
                query="查找 ticket-4821",
                context=MemoryContext(user_id="u1", space_id="s1"),
                limit=2,
            )

            self.assertEqual(
                {
                    (result.id, result.data, result.metadata["user_id"])
                    for result in results
                },
                {
                    (dense_memory_id, "用户偏好简洁回答", "u1"),
                    (keyword_memory_id, "支持工单编号 ticket-4821", "u1"),
                },
            )
        finally:
            client.close()

    def test_recalls_user_and_current_space_with_user_scope_winning_same_text(self):
        shared_text = "User prefers concise answers."

        class ScopedStore:
            def dense_search(self, *, query_vector, top_k, filters):
                if filters["space_id"] is None:
                    return [
                        MemorySearchResult(
                            id="user-shared",
                            data=shared_text,
                            scope="user",
                            score=0.9,
                            metadata={"user_id": "u1"},
                        ),
                        MemorySearchResult(
                            id="user-only",
                            data="User writes Python.",
                            scope="user",
                            score=0.8,
                            metadata={"user_id": "u1"},
                        ),
                    ]
                return [
                    MemorySearchResult(
                        id="space-shared",
                        data=shared_text,
                        scope="space",
                        score=0.95,
                        metadata={"user_id": "u1", "space_id": "s1"},
                    ),
                    MemorySearchResult(
                        id="space-only",
                        data="This repository uses Django.",
                        scope="space",
                        score=0.8,
                        metadata={"user_id": "u1", "space_id": "s1"},
                    ),
                ]

            def keyword_search(self, *, query, top_k, filters):
                return None

        memory = Memory(
            extractor=UnusedMemoryExtractor(),
            dense_encoder=FakeDenseEncoder(),
            vector_store=ScopedStore(),
        )

        results = memory.recall(
            query="How should you answer?",
            context=MemoryContext(user_id="u1", space_id="s1"),
            limit=3,
        )

        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].data, shared_text)
        self.assertEqual(results[0].scope, "user")
        self.assertEqual(
            {result.data for result in results[1:]},
            {"User writes Python.", "This repository uses Django."},
        )

    def test_reranks_twenty_candidates_down_to_requested_limit(self):
        requested_top_ks = []

        class CandidateStore:
            def dense_search(self, *, query_vector, top_k, filters):
                requested_top_ks.append(top_k)
                scope = "user" if filters["space_id"] is None else "space"
                return [
                    MemorySearchResult(
                        id=f"{scope}-{index}",
                        data=f"{scope} memory {index}",
                        scope=scope,
                        score=1 / (index + 1),
                        metadata=dict(filters),
                    )
                    for index in range(top_k)
                ]

            def keyword_search(self, *, query, top_k, filters):
                return None

        class RecordingReranker:
            candidates = []

            def rerank(self, *, query, candidates, limit):
                self.candidates = list(candidates)
                return list(reversed(candidates))[:limit]

        reranker = RecordingReranker()
        memory = Memory(
            extractor=UnusedMemoryExtractor(),
            dense_encoder=FakeDenseEncoder(),
            vector_store=CandidateStore(),
            reranker=reranker,
        )

        results = memory.recall(
            query="Which memory matters?",
            context=MemoryContext(user_id="u1", space_id="s1"),
            limit=5,
            rerank=True,
        )

        self.assertEqual(requested_top_ks, [10, 10])
        self.assertEqual(len(reranker.candidates), 20)
        self.assertEqual(results, list(reversed(reranker.candidates))[:5])
