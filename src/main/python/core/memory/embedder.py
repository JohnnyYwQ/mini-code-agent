import json
from collections.abc import Callable, Iterable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType
from qdrant_client import models

MULTILINGUAL_E5_BASE_MODEL = "intfloat/multilingual-e5-base"
MULTILINGUAL_E5_BASE_DIMENSION = 768
CUDA_EXECUTION_PROVIDER = "CUDAExecutionProvider"
CPU_EXECUTION_PROVIDER = "CPUExecutionProvider"
E5_COMPUTE_HEAVY_OPS = frozenset(
    {
        "Attention",
        "BiasGelu",
        "EmbedLayerNormalization",
        "FastGelu",
        "FusedMatMul",
        "Gelu",
        "Gemm",
        "GroupQueryAttention",
        "LayerNormalization",
        "MatMul",
        "MultiHeadAttention",
        "QAttention",
        "SimplifiedLayerNormalization",
        "SkipLayerNormalization",
        "Softmax",
    }
)


class FastEmbedE5Encoder:
    """Convert text into role-aware E5 dense vectors."""

    def __init__(
        self,
        *,
        model: Any,
        cuda_execution: dict[str, Any] | None = None,
    ) -> None:
        self.model = model
        self.cuda_execution = cuda_execution

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


def _profiled_ops_by_provider(profile_path: Path) -> dict[str, set[str]]:
    try:
        events = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"failed to read E5 CUDA profile: {profile_path}") from exc
    if not isinstance(events, list):
        raise RuntimeError("E5 CUDA profile did not contain an event list")

    profiled_ops: dict[str, set[str]] = {}
    for event in events:
        if not isinstance(event, dict) or event.get("cat") != "Node":
            continue
        args = event.get("args")
        if not isinstance(args, dict):
            continue
        provider = args.get("provider")
        op_name = args.get("op_name")
        if isinstance(provider, str) and isinstance(op_name, str):
            profiled_ops.setdefault(provider, set()).add(op_name)
    return profiled_ops


def _verify_cuda_profile(
    profile_path: Path,
    *,
    providers: tuple[str, ...],
    device_id: int,
) -> dict[str, Any]:
    profiled_ops = _profiled_ops_by_provider(profile_path)
    cuda_ops = profiled_ops.get(CUDA_EXECUTION_PROVIDER, set())
    cpu_ops = profiled_ops.get(CPU_EXECUTION_PROVIDER, set())
    cuda_compute_ops = cuda_ops.intersection(E5_COMPUTE_HEAVY_OPS)
    cpu_compute_ops = cpu_ops.intersection(E5_COMPUTE_HEAVY_OPS)

    if cpu_compute_ops:
        raise RuntimeError(
            "E5 CUDA preflight assigned compute-heavy operators to CPU: "
            f"{sorted(cpu_compute_ops)}"
        )
    if not cuda_compute_ops:
        raise RuntimeError(
            "E5 CUDA preflight did not execute a compute-heavy operator on CUDA"
        )

    return {
        "device_id": device_id,
        "providers": list(providers),
        "cuda_profiled_ops": sorted(cuda_ops),
        "cpu_profiled_ops": sorted(cpu_ops),
        "cuda_compute_ops": sorted(cuda_compute_ops),
        "cpu_compute_ops": [],
    }


def _install_strict_cuda_session(
    model: Any,
    *,
    device_id: int,
) -> dict[str, Any]:
    """Attach and profile an E5 session whose dominant compute runs on CUDA."""
    import onnxruntime as ort  # type: ignore[import-untyped]
    from fastembed.common.preprocessor_utils import load_tokenizer

    if CUDA_EXECUTION_PROVIDER not in ort.get_available_providers():
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

    with TemporaryDirectory(prefix="mini-code-agent-e5-ort-") as profile_dir:
        session_options = ort.SessionOptions()
        session_options.graph_optimization_level = (
            ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        )
        session_options.enable_profiling = True
        session_options.profile_file_prefix = str(
            Path(profile_dir) / "onnxruntime_profile"
        )
        threads = getattr(inner_model, "threads", None)
        if threads is not None:
            session_options.intra_op_num_threads = threads
            session_options.inter_op_num_threads = threads

        session = ort.InferenceSession(
            str(model_path),
            providers=[(CUDA_EXECUTION_PROVIDER, {"device_id": device_id})],
            sess_options=session_options,
        )
        session.disable_fallback()
        providers = tuple(session.get_providers())
        if not providers or providers[0] != CUDA_EXECUTION_PROVIDER:
            raise RuntimeError(
                f"E5 ONNX session did not prefer CUDA: providers={providers}"
            )
        unexpected_providers = set(providers).difference(
            {CUDA_EXECUTION_PROVIDER, CPU_EXECUTION_PROVIDER}
        )
        if unexpected_providers:
            raise RuntimeError(
                "E5 ONNX session registered unexpected providers: "
                f"{sorted(unexpected_providers)}"
            )
        cuda_options = session.get_provider_options().get(
            CUDA_EXECUTION_PROVIDER,
            {},
        )
        if str(cuda_options.get("device_id")) != str(device_id):
            raise RuntimeError(
                "E5 ONNX session selected the wrong CUDA device: "
                f"{cuda_options.get('device_id')}"
            )

        tokenizer, special_token_to_id = load_tokenizer(model_dir=Path(model_dir))
        inner_model.model = session
        inner_model.tokenizer = tokenizer
        inner_model.special_token_to_id = special_token_to_id
        try:
            probe = next(iter(model.embed(["query: CUDA preflight"], batch_size=1)))
            probe_values = list(probe.tolist())
            if len(probe_values) != MULTILINGUAL_E5_BASE_DIMENSION:
                raise RuntimeError(
                    "E5 CUDA preflight returned an unexpected vector dimension: "
                    f"{len(probe_values)}"
                )
        finally:
            profile_path = Path(session.end_profiling())

        return _verify_cuda_profile(
            profile_path,
            providers=providers,
            device_id=device_id,
        )


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
    cuda_execution = None
    if require_cuda:
        cuda_execution = _install_strict_cuda_session(model, device_id=device_id)
    return FastEmbedE5Encoder(model=model, cuda_execution=cuda_execution)


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
