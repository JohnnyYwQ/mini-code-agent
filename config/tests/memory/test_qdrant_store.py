import uuid
from unittest import TestCase

from core.memory.qdrant_store import QdrantStore
from qdrant_client import QdrantClient, models


class QdrantStoreInitializationTests(TestCase):
    collection_name = "test_memories"

    def setUp(self):
        self.client = QdrantClient(":memory:")

    def tearDown(self):
        self.client.close()

    def test_creates_collection_with_expected_vector_config(self):
        QdrantStore(
            client=self.client,
            collection_name=self.collection_name,
            dimension=3,
        )

        collection = self.client.get_collection(self.collection_name)

        self.assertEqual(collection.config.params.vectors.size, 3)
        self.assertEqual(
            collection.config.params.vectors.distance,
            models.Distance.COSINE,
        )
        self.assertIn("bm25", collection.config.params.sparse_vectors)
        self.assertEqual(
            collection.config.params.sparse_vectors["bm25"].modifier,
            models.Modifier.IDF,
        )

    def test_reuses_compatible_collection_without_losing_points(self):
        QdrantStore(
            client=self.client,
            collection_name=self.collection_name,
            dimension=3,
        )
        point_id = str(uuid.uuid4())
        self.client.upsert(
            collection_name=self.collection_name,
            wait=True,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=[0.1, 0.2, 0.3],
                    payload={"data": "保留我"},
                )
            ],
        )

        QdrantStore(
            client=self.client,
            collection_name=self.collection_name,
            dimension=3,
        )

        records = self.client.retrieve(
            collection_name=self.collection_name,
            ids=[point_id],
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].payload["data"], "保留我")

    def test_reuses_compatible_dense_only_collection_without_modifying_it(self):
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=3,
                distance=models.Distance.COSINE,
            ),
        )
        point_id = str(uuid.uuid4())
        self.client.upsert(
            collection_name=self.collection_name,
            wait=True,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=[0.1, 0.2, 0.3],
                    payload={"data": "旧数据"},
                )
            ],
        )

        QdrantStore(
            client=self.client,
            collection_name=self.collection_name,
            dimension=3,
        )

        collection = self.client.get_collection(self.collection_name)
        self.assertEqual(collection.config.params.vectors.size, 3)
        self.assertEqual(
            collection.config.params.vectors.distance,
            models.Distance.COSINE,
        )
        self.assertIsNone(collection.config.params.sparse_vectors)
        records = self.client.retrieve(
            collection_name=self.collection_name,
            ids=[point_id],
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].payload["data"], "旧数据")

    def test_rejects_dimension_mismatch_without_modifying_collection(self):
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=4,
                distance=models.Distance.COSINE,
            ),
        )
        point_id = str(uuid.uuid4())
        self.client.upsert(
            collection_name=self.collection_name,
            wait=True,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=[0.1, 0.2, 0.3, 0.4],
                    payload={"data": "不能被修改"},
                )
            ],
        )

        with self.assertRaisesRegex(ValueError, "dimension"):
            QdrantStore(
                client=self.client,
                collection_name=self.collection_name,
                dimension=3,
            )

        collection = self.client.get_collection(self.collection_name)
        self.assertEqual(collection.config.params.vectors.size, 4)
        records = self.client.retrieve(
            collection_name=self.collection_name,
            ids=[point_id],
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].payload["data"], "不能被修改")

    def test_rejects_incompatible_distance(self):
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=3,
                distance=models.Distance.DOT,
            ),
        )

        with self.assertRaisesRegex(ValueError, "distance"):
            QdrantStore(
                client=self.client,
                collection_name=self.collection_name,
                dimension=3,
            )

    def test_rejects_named_dense_vectors(self):
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config={
                "text": models.VectorParams(
                    size=3,
                    distance=models.Distance.COSINE,
                )
            },
        )

        with self.assertRaisesRegex(ValueError, "unnamed"):
            QdrantStore(
                client=self.client,
                collection_name=self.collection_name,
                dimension=3,
            )


class QdrantStoreUpsertTests(TestCase):
    collection_name = "test_memories"

    def setUp(self):
        self.client = QdrantClient(":memory:")
        self.store = QdrantStore(
            client=self.client,
            collection_name=self.collection_name,
            dimension=3,
        )

    def tearDown(self):
        self.client.close()

    def test_upserts_dense_vector_and_payload(self):
        memory_id = str(uuid.uuid4())
        vector = [1.0, 0.0, 0.0]
        payload = {"data": "我喜欢中文回答", "user_id": "u1"}

        result = self.store.upsert(
            memory_id=memory_id,
            vector=vector,
            payload=payload,
        )

        self.assertIsNone(result)
        records = self.client.retrieve(
            collection_name=self.collection_name,
            ids=[memory_id],
            with_vectors=True,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].vector, vector)
        self.assertEqual(records[0].payload, payload)

    def test_rejects_vector_with_wrong_dimension_before_writing(self):
        with self.assertRaisesRegex(ValueError, "vector dimension 2, expected 3"):
            self.store.upsert(
                memory_id=str(uuid.uuid4()),
                vector=[0.1, 0.2],
                payload={"data": "维度错误"},
            )

        count = self.client.count(
            collection_name=self.collection_name,
            exact=True,
        )
        self.assertEqual(count.count, 0)

    def test_adds_bm25_vector_from_payload_data_when_encoder_succeeds(self):
        encoded_texts = []

        class FakeBM25Encoder:
            def encode_document(self, text):
                encoded_texts.append(text)
                return models.SparseVector(
                    indices=[10, 50],
                    values=[0.8, 1.2],
                )

        store = QdrantStore(
            client=self.client,
            collection_name=self.collection_name,
            dimension=3,
            bm25_encoder=FakeBM25Encoder(),
        )
        memory_id = str(uuid.uuid4())

        store.upsert(
            memory_id=memory_id,
            vector=[1.0, 0.0, 0.0],
            payload={"data": "我喜欢中文回答", "user_id": "u1"},
        )

        records = self.client.retrieve(
            collection_name=self.collection_name,
            ids=[memory_id],
            with_vectors=True,
        )
        self.assertEqual(encoded_texts, ["我喜欢中文回答"])
        self.assertEqual(records[0].vector[""], [1.0, 0.0, 0.0])
        self.assertEqual(records[0].vector["bm25"].indices, [10, 50])
        self.assertEqual(records[0].vector["bm25"].values, [0.8, 1.2])

    def test_skips_bm25_encoder_for_dense_only_collection(self):
        collection_name = "dense_only_memories"
        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=3,
                distance=models.Distance.COSINE,
            ),
        )
        encoded_texts = []

        class FakeBM25Encoder:
            def encode_document(self, text):
                encoded_texts.append(text)
                return models.SparseVector(indices=[10], values=[0.8])

        store = QdrantStore(
            client=self.client,
            collection_name=collection_name,
            dimension=3,
            bm25_encoder=FakeBM25Encoder(),
        )
        memory_id = str(uuid.uuid4())

        store.upsert(
            memory_id=memory_id,
            vector=[1.0, 0.0, 0.0],
            payload={"data": "只写语义向量"},
        )

        self.assertEqual(encoded_texts, [])
        records = self.client.retrieve(
            collection_name=collection_name,
            ids=[memory_id],
            with_vectors=True,
        )
        self.assertEqual(records[0].vector, [1.0, 0.0, 0.0])

    def test_stores_dense_vector_when_bm25_encoder_fails(self):
        class BrokenBM25Encoder:
            def encode_document(self, text):
                raise RuntimeError("BM25 编码失败")

        store = QdrantStore(
            client=self.client,
            collection_name=self.collection_name,
            dimension=3,
            bm25_encoder=BrokenBM25Encoder(),
        )
        memory_id = str(uuid.uuid4())
        payload = {"data": "仍然保存这条记忆", "user_id": "u1"}

        store.upsert(
            memory_id=memory_id,
            vector=[1.0, 0.0, 0.0],
            payload=payload,
        )

        records = self.client.retrieve(
            collection_name=self.collection_name,
            ids=[memory_id],
            with_vectors=True,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].vector, [1.0, 0.0, 0.0])
        self.assertEqual(records[0].payload, payload)


class QdrantStoreDenseSearchTests(TestCase):
    collection_name = "test_dense_search_memories"

    def setUp(self):
        self.client = QdrantClient(":memory:")
        self.store = QdrantStore(
            client=self.client,
            collection_name=self.collection_name,
            dimension=3,
        )

    def tearDown(self):
        self.client.close()

    def test_returns_nearest_dense_match(self):
        related_memory_id = str(uuid.uuid4())
        unrelated_memory_id = str(uuid.uuid4())
        self.store.upsert(
            memory_id=related_memory_id,
            vector=[1.0, 0.0, 0.0],
            payload={"data": "用户喜欢使用中文回答"},
        )
        self.store.upsert(
            memory_id=unrelated_memory_id,
            vector=[0.0, 1.0, 0.0],
            payload={"data": "用户周末喜欢去公园跑步"},
        )

        results = self.store.dense_search(
            query_vector=[1.0, 0.0, 0.0],
            top_k=1,
        )

        self.assertEqual([point.id for point in results], [related_memory_id])
        self.assertEqual(results[0].data, "用户喜欢使用中文回答")

    def test_returns_empty_list_for_empty_collection(self):
        results = self.store.dense_search(
            query_vector=[1.0, 0.0, 0.0],
        )

        self.assertEqual(results, [])

    def test_rejects_query_vector_with_wrong_dimension(self):
        with self.assertRaisesRegex(
            ValueError,
            "query vector dimension 2, expected 3",
        ):
            self.store.dense_search(
                query_vector=[1.0, 0.0],
            )


class QdrantStoreKeywordSearchTests(TestCase):
    collection_name = "test_keyword_memories"

    def setUp(self):
        self.client = QdrantClient(":memory:")

    def tearDown(self):
        self.client.close()

    def test_returns_bm25_matches_from_query_embedding(self):
        encoded_queries = []

        class FakeBM25Encoder:
            def encode_document(self, text):
                return models.SparseVector(
                    indices=[10, 50],
                    values=[0.8, 1.2],
                )

            def encode_query(self, text):
                encoded_queries.append(text)
                return models.SparseVector(
                    indices=[10],
                    values=[1.0],
                )

        store = QdrantStore(
            client=self.client,
            collection_name=self.collection_name,
            dimension=3,
            bm25_encoder=FakeBM25Encoder(),
        )
        memory_id = str(uuid.uuid4())
        payload = {"data": "我喜欢中文回答", "user_id": "u1"}
        store.upsert(
            memory_id=memory_id,
            vector=[1.0, 0.0, 0.0],
            payload=payload,
        )

        results = store.keyword_search(query="中文", top_k=5)

        self.assertEqual(encoded_queries, ["中文"])
        self.assertIsNotNone(results)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, memory_id)
        self.assertEqual(results[0].data, "我喜欢中文回答")
        self.assertEqual(results[0].metadata, {"user_id": "u1"})

    def test_returns_none_and_logs_warning_when_query_encoding_fails(self):
        class BrokenBM25Encoder:
            def encode_document(self, text):
                return models.SparseVector(indices=[10], values=[1.0])

            def encode_query(self, text):
                raise RuntimeError("BM25 query encoding failed")

        store = QdrantStore(
            client=self.client,
            collection_name=self.collection_name,
            dimension=3,
            bm25_encoder=BrokenBM25Encoder(),
        )

        with self.assertLogs("core.memory.qdrant_store", level="WARNING") as logs:
            results = store.keyword_search(query="中文")

        self.assertIsNone(results)
        self.assertIn("BM25 query encoding failed", "\n".join(logs.output))

    def test_returns_none_without_encoding_for_dense_only_collection(self):
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=3,
                distance=models.Distance.COSINE,
            ),
        )
        encoded_queries = []

        class FakeBM25Encoder:
            def encode_document(self, text):
                return models.SparseVector(indices=[10], values=[1.0])

            def encode_query(self, text):
                encoded_queries.append(text)
                return models.SparseVector(indices=[10], values=[1.0])

        store = QdrantStore(
            client=self.client,
            collection_name=self.collection_name,
            dimension=3,
            bm25_encoder=FakeBM25Encoder(),
        )

        results = store.keyword_search(query="中文")

        self.assertIsNone(results)
        self.assertEqual(encoded_queries, [])

    def test_returns_none_when_bm25_encoder_is_not_configured(self):
        store = QdrantStore(
            client=self.client,
            collection_name=self.collection_name,
            dimension=3,
        )

        results = store.keyword_search(query="中文")

        self.assertIsNone(results)

    def test_returns_none_when_query_encoder_returns_none(self):
        encoded_queries = []

        class EmptyBM25Encoder:
            def encode_document(self, text):
                return models.SparseVector(indices=[10], values=[1.0])

            def encode_query(self, text):
                encoded_queries.append(text)
                return None

        store = QdrantStore(
            client=self.client,
            collection_name=self.collection_name,
            dimension=3,
            bm25_encoder=EmptyBM25Encoder(),
        )

        results = store.keyword_search(query="中文")

        self.assertEqual(encoded_queries, ["中文"])
        self.assertIsNone(results)

    def test_returns_empty_list_when_bm25_query_has_no_matches(self):
        encoded_queries = []

        class FakeBM25Encoder:
            def encode_document(self, text):
                return models.SparseVector(indices=[10], values=[1.0])

            def encode_query(self, text):
                encoded_queries.append(text)
                return models.SparseVector(indices=[10], values=[1.0])

        store = QdrantStore(
            client=self.client,
            collection_name=self.collection_name,
            dimension=3,
            bm25_encoder=FakeBM25Encoder(),
        )

        results = store.keyword_search(query="中文")

        self.assertEqual(encoded_queries, ["中文"])
        self.assertEqual(results, [])

    def test_limits_bm25_results_to_top_k(self):
        class FakeBM25Encoder:
            def encode_document(self, text):
                return models.SparseVector(indices=[10], values=[1.0])

            def encode_query(self, text):
                return models.SparseVector(indices=[10], values=[1.0])

        store = QdrantStore(
            client=self.client,
            collection_name=self.collection_name,
            dimension=3,
            bm25_encoder=FakeBM25Encoder(),
        )
        for position in range(3):
            store.upsert(
                memory_id=str(uuid.uuid4()),
                vector=[1.0, 0.0, 0.0],
                payload={"data": f"memory {position}"},
            )

        results = store.keyword_search(query="memory", top_k=2)

        self.assertIsNotNone(results)
        self.assertEqual(len(results), 2)

    def test_filters_bm25_results_by_user_id(self):
        class FakeBM25Encoder:
            def encode_document(self, text):
                return models.SparseVector(indices=[10], values=[1.0])

            def encode_query(self, text):
                return models.SparseVector(indices=[10], values=[1.0])

        store = QdrantStore(
            client=self.client,
            collection_name=self.collection_name,
            dimension=3,
            bm25_encoder=FakeBM25Encoder(),
        )
        user_one_memory_id = str(uuid.uuid4())
        user_two_memory_id = str(uuid.uuid4())
        for memory_id, user_id in (
            (user_one_memory_id, "u1"),
            (user_two_memory_id, "u2"),
        ):
            store.upsert(
                memory_id=memory_id,
                vector=[1.0, 0.0, 0.0],
                payload={"data": "相同内容", "user_id": user_id},
            )

        results = store.keyword_search(
            query="相同内容",
            filters={"user_id": "u1"},
        )

        self.assertIsNotNone(results)
        self.assertEqual([point.id for point in results], [user_one_memory_id])
