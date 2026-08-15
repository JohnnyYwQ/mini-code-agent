import os
import uuid
from unittest import TestCase, skipUnless

from core.memory.embedder import build_multilingual_e5_base_encoder
from core.memory.qdrant_store import QdrantStore
from qdrant_client import QdrantClient


@skipUnless(os.getenv("RUN_E5_SMOKE") == "1", "real E5 smoke test is opt-in")
class MultilingualE5BaseSmokeTests(TestCase):
    def test_retrieves_related_chinese_memory_with_user_scope(self):
        encoder = build_multilingual_e5_base_encoder()
        client = QdrantClient(":memory:")
        store = QdrantStore(
            client=client,
            collection_name="multilingual_e5_base_smoke",
            dimension=768,
        )
        related_memory_id = str(uuid.uuid4())
        memories = [
            (
                related_memory_id,
                "用户喜欢使用中文回答",
                "u1",
            ),
            (
                str(uuid.uuid4()),
                "用户周末喜欢去公园跑步",
                "u1",
            ),
            (
                str(uuid.uuid4()),
                "用户喜欢使用中文回答",
                "u2",
            ),
        ]

        try:
            for memory_id, text, user_id in memories:
                store.upsert(
                    memory_id=memory_id,
                    vector=encoder.encode_document(text),
                    payload={"data": text, "user_id": user_id},
                )

            results = store.dense_search(
                query_vector=encoder.encode_query("用户偏好使用什么语言回答？"),
                top_k=2,
                filters={"user_id": "u1"},
            )

            self.assertEqual(results[0].id, related_memory_id)
            self.assertEqual(
                [point.metadata["user_id"] for point in results], ["u1", "u1"]
            )
        finally:
            client.close()
