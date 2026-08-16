from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType
from qdrant_client import models

MULTILINGUAL_E5_BASE_MODEL = "intfloat/multilingual-e5-base"
MULTILINGUAL_E5_BASE_DIMENSION = 768


class FastEmbedE5Encoder:
    """Convert text into role-aware E5 dense vectors."""

    def __init__(self, *, model: Any) -> None:
        self.model = model

    def encode_document(self, text: str) -> list[float]:
        """Encode memory text as an E5 passage."""
        return self._encode(f"passage: {text}")

    def encode_query(self, text: str) -> list[float]:
        """Encode search text as an E5 query."""
        return self._encode(f"query: {text}")

    def encode_documents(
        self,
        texts: Iterable[str],
        *,
        batch_size: int,
    ) -> list[list[float]]:
        """Encode multiple memory texts in one FastEmbed batch stream."""
        return self._encode_many(texts, prefix="passage: ", batch_size=batch_size)

    def encode_queries(
        self,
        texts: Iterable[str],
        *,
        batch_size: int,
    ) -> list[list[float]]:
        """Encode multiple search texts in one FastEmbed batch stream."""
        return self._encode_many(texts, prefix="query: ", batch_size=batch_size)

    @property
    def execution_providers(self) -> tuple[str, ...]:
        """Return the ONNX Runtime providers attached to the dense model."""
        session = _fastembed_onnx_session(self.model)
        return tuple(session.get_providers())

    def _encode(self, text: str) -> list[float]:
        vectors = self._encode_many([text], prefix="", batch_size=1)
        if not vectors:
            raise RuntimeError("E5 model returned no embedding")
        return vectors[0]

    def _encode_many(
        self,
        texts: Iterable[str],
        *,
        prefix: str,
        batch_size: int,
    ) -> list[list[float]]:
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        prepared = [f"{prefix}{text}" for text in texts]
        if not prepared:
            return []
        return [
            list(embedding.tolist())
            for embedding in self.model.embed(prepared, batch_size=batch_size)
        ]


def _fastembed_onnx_session(model: Any) -> Any:
    inner_model = getattr(model, "model", None)
    session = getattr(inner_model, "model", None)
    if session is None or not hasattr(session, "get_providers"):
        raise RuntimeError("FastEmbed did not expose an initialized ONNX session")
    return session


def _require_torch_cuda(*, device_id: int) -> None:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; refusing to run E5 on CPU")
    if device_id < 0 or device_id >= torch.cuda.device_count():
        raise RuntimeError(f"CUDA device {device_id} is unavailable")
    torch.cuda.set_device(device_id)
    torch.empty(1, device=f"cuda:{device_id}")


def _install_strict_cuda_session(model: Any, *, device_id: int) -> None:
    """Attach an ONNX session that rejects graph or runtime CPU fallback."""
    import onnxruntime as ort  # type: ignore[import-untyped]
    from fastembed.common.preprocessor_utils import load_tokenizer

    if "CUDAExecutionProvider" not in ort.get_available_providers():
        raise RuntimeError(
            "ONNX Runtime CUDAExecutionProvider is unavailable; "
            "refusing to run E5 on CPU"
        )

    inner_model = getattr(model, "model", None)
    model_dir = getattr(inner_model, "_model_dir", None)
    model_description = getattr(inner_model, "model_description", None)
    model_file = getattr(model_description, "model_file", None)
    if inner_model is None or model_dir is None or not isinstance(model_file, str):
        raise RuntimeError(
            "FastEmbed model internals are incompatible with strict CUDA"
        )

    model_path = Path(model_dir) / model_file
    if not model_path.is_file():
        raise RuntimeError(f"E5 ONNX model is missing: {model_path}")

    session_options = ort.SessionOptions()
    session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session_options.add_session_config_entry("session.disable_cpu_ep_fallback", "1")
    threads = getattr(inner_model, "threads", None)
    if threads is not None:
        session_options.intra_op_num_threads = threads
        session_options.inter_op_num_threads = threads

    session = ort.InferenceSession(
        str(model_path),
        providers=[("CUDAExecutionProvider", {"device_id": device_id})],
        sess_options=session_options,
    )
    session.disable_fallback()
    providers = tuple(session.get_providers())
    if providers != ("CUDAExecutionProvider",):
        raise RuntimeError(
            f"E5 ONNX session did not remain CUDA-only: providers={providers}"
        )

    tokenizer, special_token_to_id = load_tokenizer(model_dir=Path(model_dir))
    inner_model.model = session
    inner_model.tokenizer = tokenizer
    inner_model.special_token_to_id = special_token_to_id


def build_multilingual_e5_base_encoder(
    *,
    cache_dir: str | Path | None = None,
    model_path: str | Path | None = None,
    require_cuda: bool = False,
    device_id: int = 0,
) -> FastEmbedE5Encoder:
    """Build an encoder backed by intfloat/multilingual-e5-base."""
    supported_models = TextEmbedding.list_supported_models()
    if not any(
        description["model"] == MULTILINGUAL_E5_BASE_MODEL
        for description in supported_models
    ):
        TextEmbedding.add_custom_model(
            model=MULTILINGUAL_E5_BASE_MODEL,
            pooling=PoolingType.MEAN,
            normalization=True,
            sources=ModelSource(hf=MULTILINGUAL_E5_BASE_MODEL),
            dim=MULTILINGUAL_E5_BASE_DIMENSION,
            model_file="onnx/model.onnx",
        )

    model_kwargs: dict[str, Any] = {
        "model_name": MULTILINGUAL_E5_BASE_MODEL,
    }
    if cache_dir is not None:
        model_kwargs["cache_dir"] = str(cache_dir)
    if model_path is not None:
        model_kwargs["specific_model_path"] = str(model_path)
    if require_cuda:
        _require_torch_cuda(device_id=device_id)
        model_kwargs.update(
            {
                "providers": [
                    ("CUDAExecutionProvider", {"device_id": device_id}),
                ],
                "lazy_load": True,
            }
        )

    model = TextEmbedding(**model_kwargs)
    if require_cuda:
        _install_strict_cuda_session(model, device_id=device_id)
    return FastEmbedE5Encoder(model=model)


class FastEmbedBM25Encoder:
    """Convert text into a Qdrant BM25 sparse vector."""

    def __init__(
        self,
        *,
        model: Any,
        chinese_segmenter: Callable[[str], Iterable[str]],
    ) -> None:
        self.model = model
        self.chinese_segmenter = chinese_segmenter

    def encode_document(self, text: str) -> models.SparseVector:
        """Encode memory text with BM25 document weighting."""
        vectors = self.encode_documents([text], batch_size=1)
        if not vectors:
            raise RuntimeError("BM25 model returned no embedding")
        return vectors[0]

    def encode_query(self, text: str) -> models.SparseVector:
        """Encode search text with BM25 query weighting."""
        vectors = self.encode_queries([text], batch_size=1)
        if not vectors:
            raise RuntimeError("BM25 model returned no embedding")
        return vectors[0]

    def encode_documents(
        self,
        texts: Iterable[str],
        *,
        batch_size: int,
    ) -> list[models.SparseVector]:
        """Encode multiple BM25 documents in one FastEmbed stream."""
        return self._encode_many(texts, batch_size=batch_size, query=False)

    def encode_queries(
        self,
        texts: Iterable[str],
        *,
        batch_size: int,
    ) -> list[models.SparseVector]:
        """Encode multiple BM25 queries in one FastEmbed stream."""
        return self._encode_many(texts, batch_size=batch_size, query=True)

    def _encode_many(
        self,
        texts: Iterable[str],
        *,
        batch_size: int,
        query: bool,
    ) -> list[models.SparseVector]:
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        prepared = [self._prepare_text(text) for text in texts]
        if not prepared:
            return []
        embed = self.model.query_embed if query else self.model.embed
        return [
            self._to_sparse_vector([embedding])
            for embedding in embed(prepared, batch_size=batch_size)
        ]

    def _to_sparse_vector(self, embeddings: Iterable[Any]) -> models.SparseVector:
        try:
            embedding = next(iter(embeddings))
        except StopIteration as exc:
            raise RuntimeError("BM25 model returned no embedding") from exc
        return models.SparseVector(
            indices=embedding.indices.tolist(),
            values=embedding.values.tolist(),
        )

    def _prepare_text(self, text: str) -> str:
        contains_chinese = any("\u4e00" <= char <= "\u9fff" for char in text)
        return " ".join(self.chinese_segmenter(text)) if contains_chinese else text
