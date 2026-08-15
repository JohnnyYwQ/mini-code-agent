from unittest import TestCase
from unittest.mock import patch

from core.memory.embedder import (
    FastEmbedBM25Encoder,
    FastEmbedE5Encoder,
    build_multilingual_e5_base_encoder,
)
from fastembed.common.model_description import PoolingType
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


class RecordingDenseModel:
    def __init__(self):
        self.encoded_texts = []

    def embed(self, texts):
        [text] = texts
        self.encoded_texts.append(text)
        if text.startswith("passage: "):
            return iter([FakeArray([0.1, 0.2, 0.3])])
        return iter([FakeArray([0.4, 0.5, 0.6])])


class FastEmbedE5EncoderTests(TestCase):
    def test_adds_e5_roles_before_dense_encoding(self):
        model = RecordingDenseModel()
        encoder = FastEmbedE5Encoder(model=model)

        document_vector = encoder.encode_document("我喜欢中文回答")
        query_vector = encoder.encode_query("怎么用中文回答？")

        self.assertEqual(
            model.encoded_texts,
            [
                "passage: 我喜欢中文回答",
                "query: 怎么用中文回答？",
            ],
        )
        self.assertEqual(document_vector, [0.1, 0.2, 0.3])
        self.assertEqual(query_vector, [0.4, 0.5, 0.6])


class MultilingualE5BaseBuilderTests(TestCase):
    @patch("core.memory.embedder.TextEmbedding")
    def test_registers_and_builds_exact_model(self, text_embedding):
        text_embedding.list_supported_models.return_value = []
        model = object()
        text_embedding.return_value = model

        encoder = build_multilingual_e5_base_encoder()

        registration = text_embedding.add_custom_model.call_args.kwargs
        self.assertEqual(registration["model"], "intfloat/multilingual-e5-base")
        self.assertEqual(registration["pooling"], PoolingType.MEAN)
        self.assertIs(registration["normalization"], True)
        self.assertEqual(registration["sources"].hf, "intfloat/multilingual-e5-base")
        self.assertEqual(registration["dim"], 768)
        self.assertEqual(registration["model_file"], "onnx/model.onnx")
        text_embedding.assert_called_once_with(
            model_name="intfloat/multilingual-e5-base"
        )
        self.assertIs(encoder.model, model)

    @patch("core.memory.embedder.TextEmbedding")
    def test_builds_registered_model_without_registering_it_again(self, text_embedding):
        text_embedding.list_supported_models.return_value = [
            {"model": "intfloat/multilingual-e5-base"}
        ]
        model = object()
        text_embedding.return_value = model

        encoder = build_multilingual_e5_base_encoder()

        text_embedding.add_custom_model.assert_not_called()
        text_embedding.assert_called_once_with(
            model_name="intfloat/multilingual-e5-base"
        )
        self.assertIs(encoder.model, model)


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
