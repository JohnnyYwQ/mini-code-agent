from unittest import TestCase

from core.memory.embedder import FastEmbedBM25Encoder
from qdrant_client import models


class FakeArray:
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return self.values


class FakeSparseEmbedding:
    def __init__(self, indices, values):
        self.indices = FakeArray(indices)
        self.values = FakeArray(values)


class FakeSparseModel:
    def embed(self, documents):
        [document] = documents
        if document == "我 喜欢 中文 回答":
            embedding = FakeSparseEmbedding([12, 40], [0.5, 1.25])
        elif document == "machine learning":
            embedding = FakeSparseEmbedding([7, 21], [0.7, 1.1])
        else:
            embedding = FakeSparseEmbedding([99], [0.01])
        return iter([embedding])

    def query_embed(self, queries):
        [query] = queries
        if query == "我 喜欢 中文 回答":
            embedding = FakeSparseEmbedding([12, 40], [1.0, 1.0])
        elif query == "machine learning":
            embedding = FakeSparseEmbedding([7, 21], [1.0, 1.0])
        else:
            embedding = FakeSparseEmbedding([99], [1.0])
        return iter([embedding])


class EmptySparseModel:
    def embed(self, documents):
        return iter([])


class FastEmbedBM25EncoderTests(TestCase):
    def test_segments_chinese_before_sparse_encoding(self):
        model = FakeSparseModel()

        def segment_chinese(text):
            return ["我", "喜欢", "中文", "回答"]

        encoder = FastEmbedBM25Encoder(
            model=model,
            chinese_segmenter=segment_chinese,
        )

        vector = encoder.encode_document("我喜欢中文回答")

        self.assertEqual(
            vector,
            models.SparseVector(
                indices=[12, 40],
                values=[0.5, 1.25],
            ),
        )

    def test_encodes_english_document_without_segmentation(self):
        encoder = FastEmbedBM25Encoder(
            model=FakeSparseModel(),
            chinese_segmenter=lambda text: ["should", "not", "be", "used"],
        )

        vector = encoder.encode_document("machine learning")

        self.assertEqual(
            vector,
            models.SparseVector(
                indices=[7, 21],
                values=[0.7, 1.1],
            ),
        )

    def test_encodes_english_query_with_query_weighting(self):
        encoder = FastEmbedBM25Encoder(
            model=FakeSparseModel(),
            chinese_segmenter=lambda text: ["should", "not", "be", "used"],
        )

        vector = encoder.encode_query("machine learning")

        self.assertEqual(
            vector,
            models.SparseVector(
                indices=[7, 21],
                values=[1.0, 1.0],
            ),
        )

    def test_segments_chinese_query_before_query_encoding(self):
        encoder = FastEmbedBM25Encoder(
            model=FakeSparseModel(),
            chinese_segmenter=lambda text: ["我", "喜欢", "中文", "回答"],
        )

        vector = encoder.encode_query("我喜欢中文回答")

        self.assertEqual(
            vector,
            models.SparseVector(
                indices=[12, 40],
                values=[1.0, 1.0],
            ),
        )

    def test_raises_clear_error_when_model_produces_no_embedding(self):
        encoder = FastEmbedBM25Encoder(
            model=EmptySparseModel(),
            chinese_segmenter=lambda text: [text],
        )

        with self.assertRaisesRegex(RuntimeError, "no embedding"):
            encoder.encode_document("valid memory")
