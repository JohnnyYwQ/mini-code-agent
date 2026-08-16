import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from core.memory.embedder import (
    FastEmbedBM25Encoder,
    FastEmbedE5Encoder,
    _install_strict_cuda_session,
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
    def __init__(self):
        self.batch_sizes = []

    def _embedding(self, document, *, query):
        if document == "我 喜欢 中文 回答":
            values = [1.0, 1.0] if query else [0.5, 1.25]
            return FakeSparseEmbedding([12, 40], values)
        elif document == "machine learning":
            values = [1.0, 1.0] if query else [0.7, 1.1]
            return FakeSparseEmbedding([7, 21], values)
        return FakeSparseEmbedding([99], [1.0] if query else [0.01])

    def embed(self, documents, *, batch_size):
        self.batch_sizes.append(batch_size)
        return iter(self._embedding(document, query=False) for document in documents)

    def query_embed(self, queries, *, batch_size):
        self.batch_sizes.append(batch_size)
        return iter(self._embedding(query, query=True) for query in queries)


class EmptySparseModel:
    def embed(self, documents, *, batch_size):
        return iter([])


class RecordingDenseModel:
    def __init__(self):
        self.encoded_texts = []
        self.batch_sizes = []

    def embed(self, texts, *, batch_size):
        self.encoded_texts.extend(texts)
        self.batch_sizes.append(batch_size)
        return iter(
            FakeArray([0.1, 0.2, 0.3])
            if text.startswith("passage: ")
            else FakeArray([0.4, 0.5, 0.6])
            for text in texts
        )


class FakeCudaSessionOptions:
    def __init__(self):
        self.config_entries = {}
        self.enable_profiling = False
        self.graph_optimization_level = None
        self.inter_op_num_threads = 0
        self.intra_op_num_threads = 0
        self.profile_file_prefix = ""

    def add_session_config_entry(self, name, value):
        self.config_entries[name] = value


class FakeCudaSession:
    profile_events = []

    def __init__(self, model_path, *, providers, sess_options):
        if sess_options.config_entries.get("session.disable_cpu_ep_fallback") == "1":
            raise RuntimeError(
                "This session contains graph nodes that are assigned to the "
                "default CPU EP, but fallback to CPU EP has been explicitly disabled"
            )
        self.model_path = model_path
        self.requested_providers = providers
        self.sess_options = sess_options
        self.fallback_disabled = False

    def disable_fallback(self):
        self.fallback_disabled = True

    def get_providers(self):
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]

    def get_provider_options(self):
        return {"CUDAExecutionProvider": {"device_id": "0"}}

    def end_profiling(self):
        profile_path = Path(f"{self.sess_options.profile_file_prefix}_test.json")
        profile_path.write_text(json.dumps(self.profile_events), encoding="utf-8")
        return str(profile_path)


class FakeFastEmbedCudaModel:
    def __init__(self, model_dir):
        self.model = SimpleNamespace(
            _model_dir=model_dir,
            model_description=SimpleNamespace(model_file="onnx/model.onnx"),
            threads=2,
            model=None,
            tokenizer=None,
            special_token_to_id=None,
        )
        self.encoded_texts = []

    def embed(self, texts, *, batch_size):
        self.encoded_texts.extend(texts)
        return iter([FakeArray([0.0] * 768)])


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
        self.assertEqual(model.batch_sizes, [1, 1])

    def test_batches_role_aware_dense_encoding(self):
        model = RecordingDenseModel()
        encoder = FastEmbedE5Encoder(model=model)

        documents = encoder.encode_documents(["one", "two"], batch_size=8)
        queries = encoder.encode_queries(["three", "four"], batch_size=4)

        self.assertEqual(
            model.encoded_texts,
            ["passage: one", "passage: two", "query: three", "query: four"],
        )
        self.assertEqual(model.batch_sizes, [8, 4])
        self.assertEqual(documents, [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]])
        self.assertEqual(queries, [[0.4, 0.5, 0.6], [0.4, 0.5, 0.6]])

    def test_rejects_non_positive_batch_size(self):
        encoder = FastEmbedE5Encoder(model=RecordingDenseModel())

        with self.assertRaisesRegex(ValueError, "batch_size"):
            encoder.encode_documents(["one"], batch_size=0)


class MultilingualE5BaseBuilderTests(TestCase):
    def _install_fake_cuda_session(self, *, profile_events):
        FakeCudaSession.profile_events = profile_events
        with TemporaryDirectory() as temp_dir:
            model_dir = Path(temp_dir)
            model_path = model_dir / "onnx" / "model.onnx"
            model_path.parent.mkdir()
            model_path.touch()
            model = FakeFastEmbedCudaModel(model_dir)
            fake_ort = SimpleNamespace(
                GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL="all"),
                InferenceSession=FakeCudaSession,
                SessionOptions=FakeCudaSessionOptions,
                get_available_providers=lambda: [
                    "CUDAExecutionProvider",
                    "CPUExecutionProvider",
                ],
            )
            with (
                patch.dict(sys.modules, {"onnxruntime": fake_ort}),
                patch(
                    "fastembed.common.preprocessor_utils.load_tokenizer",
                    return_value=("tokenizer", {"[PAD]": 0}),
                ),
            ):
                evidence = _install_strict_cuda_session(model, device_id=0)
            return model, evidence

    def test_cuda_preflight_allows_ort_cpu_shape_nodes(self):
        model, evidence = self._install_fake_cuda_session(
            profile_events=[
                {
                    "cat": "Node",
                    "args": {
                        "op_name": "Shape",
                        "provider": "CPUExecutionProvider",
                    },
                },
                {
                    "cat": "Node",
                    "args": {
                        "op_name": "MatMul",
                        "provider": "CUDAExecutionProvider",
                    },
                },
            ]
        )

        session = model.model.model
        self.assertTrue(session.fallback_disabled)
        self.assertNotIn(
            "session.disable_cpu_ep_fallback",
            session.sess_options.config_entries,
        )
        self.assertTrue(session.sess_options.enable_profiling)
        self.assertEqual(model.encoded_texts, ["query: CUDA preflight"])
        self.assertEqual(
            evidence,
            {
                "device_id": 0,
                "providers": [
                    "CUDAExecutionProvider",
                    "CPUExecutionProvider",
                ],
                "cuda_profiled_ops": ["MatMul"],
                "cpu_profiled_ops": ["Shape"],
                "cuda_compute_ops": ["MatMul"],
                "cpu_compute_ops": [],
            },
        )

    def test_cuda_preflight_rejects_compute_heavy_cpu_fallback(self):
        with self.assertRaisesRegex(RuntimeError, "compute-heavy.*CPU"):
            self._install_fake_cuda_session(
                profile_events=[
                    {
                        "cat": "Node",
                        "args": {
                            "op_name": "MatMul",
                            "provider": "CPUExecutionProvider",
                        },
                    },
                    {
                        "cat": "Node",
                        "args": {
                            "op_name": "Shape",
                            "provider": "CUDAExecutionProvider",
                        },
                    },
                ]
            )

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

    @patch("core.memory.embedder._install_strict_cuda_session")
    @patch("core.memory.embedder._require_torch_cuda")
    @patch("core.memory.embedder.TextEmbedding")
    def test_builds_pinned_model_with_strict_cuda_session(
        self,
        text_embedding,
        require_torch_cuda,
        install_strict_cuda_session,
    ):
        text_embedding.list_supported_models.return_value = [
            {"model": "intfloat/multilingual-e5-base"}
        ]
        model = object()
        text_embedding.return_value = model

        encoder = build_multilingual_e5_base_encoder(
            cache_dir="/models/cache",
            model_path="/models/e5/snapshot",
            require_cuda=True,
            device_id=1,
        )

        require_torch_cuda.assert_called_once_with(device_id=1)
        text_embedding.assert_called_once_with(
            model_name="intfloat/multilingual-e5-base",
            cache_dir="/models/cache",
            specific_model_path="/models/e5/snapshot",
            providers=[("CUDAExecutionProvider", {"device_id": 1})],
            lazy_load=True,
        )
        install_strict_cuda_session.assert_called_once_with(model, device_id=1)
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

    def test_batches_documents_and_queries(self):
        model = FakeSparseModel()
        encoder = FastEmbedBM25Encoder(
            model=model,
            chinese_segmenter=lambda text: ["我", "喜欢", "中文", "回答"],
        )

        documents = encoder.encode_documents(
            ["我喜欢中文回答", "machine learning"],
            batch_size=16,
        )
        queries = encoder.encode_queries(["machine learning"], batch_size=8)

        self.assertEqual(model.batch_sizes, [16, 8])
        self.assertEqual(documents[0].indices, [12, 40])
        self.assertEqual(documents[1].values, [0.7, 1.1])
        self.assertEqual(queries[0].values, [1.0, 1.0])
