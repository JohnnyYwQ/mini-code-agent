from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any, Protocol

from core.memory.vector_store import MemorySearchResult

DEFAULT_BGE_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"


class BGEScoringModel(Protocol):
    def compute_score(
        self,
        sentence_pairs: list[list[str]],
        *,
        normalize: bool,
    ) -> Sequence[float] | float: ...


def _load_bge_model(
    model_name: str,
    *,
    use_fp16: bool,
    device: str | None,
    batch_size: int,
    max_length: int,
) -> BGEScoringModel:
    from FlagEmbedding import FlagReranker  # type: ignore[import-untyped]

    return FlagReranker(
        model_name,
        use_fp16=use_fp16,
        devices=[device] if device is not None else None,
        batch_size=batch_size,
        max_length=max_length,
    )


def _require_cuda_device(device: str) -> None:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; refusing to run BGE on CPU")
    if device != "cuda:0" or torch.cuda.device_count() < 1:
        raise RuntimeError(f"required CUDA device is unavailable: {device}")
    torch.cuda.set_device(0)
    torch.empty(1, device=device)


def _inspect_cuda_model(model: BGEScoringModel) -> dict[str, Any]:
    import torch

    target_devices = tuple(getattr(model, "target_devices", ()))
    if target_devices != ("cuda:0",):
        raise RuntimeError(
            f"BGE target device assertion failed: devices={target_devices}"
        )

    backing_model = getattr(model, "model", None)
    if backing_model is None or not hasattr(backing_model, "parameters"):
        raise RuntimeError("BGE did not expose its PyTorch model")
    parameters = list(backing_model.parameters())
    if not parameters:
        raise RuntimeError("BGE model has no parameters")
    parameter_devices = {str(parameter.device) for parameter in parameters}
    if parameter_devices != {"cuda:0"}:
        raise RuntimeError(
            f"BGE parameters are not CUDA-only: devices={parameter_devices}"
        )
    floating_dtypes = {
        str(parameter.dtype)
        for parameter in parameters
        if parameter.is_floating_point()
    }
    if floating_dtypes != {"torch.float16"}:
        raise RuntimeError(
            f"BGE floating parameters are not FP16-only: dtypes={floating_dtypes}"
        )
    return {
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "cuda_device": torch.cuda.get_device_name(0),
        "target_devices": list(target_devices),
        "parameter_devices": sorted(parameter_devices),
        "floating_parameter_dtypes": sorted(floating_dtypes),
    }


class BGEReranker:
    """Lazily load BGE and rerank Memory retrieval candidates."""

    def __init__(
        self,
        model_name: str = DEFAULT_BGE_RERANKER_MODEL,
        *,
        model_factory: Callable[[str], BGEScoringModel] | None = None,
        use_fp16: bool = False,
        device: str | None = None,
        batch_size: int = 128,
        max_length: int = 512,
        require_cuda: bool = False,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        if max_length <= 0:
            raise ValueError("max_length must be greater than zero")
        if require_cuda and device != "cuda:0":
            raise ValueError("strict BGE evaluation requires device='cuda:0'")
        if require_cuda and not use_fp16:
            raise ValueError("strict BGE evaluation requires FP16")
        self.model_name = model_name
        self._model_factory = model_factory
        self.use_fp16 = use_fp16
        self.device = device
        self.batch_size = batch_size
        self.max_length = max_length
        self.require_cuda = require_cuda
        self._model: BGEScoringModel | None = None
        self._runtime: dict[str, Any] | None = None

    def rerank(
        self,
        *,
        query: str,
        candidates: Sequence[MemorySearchResult],
        limit: int,
    ) -> list[MemorySearchResult]:
        if limit <= 0 or not candidates:
            return []

        raw_scores = self._get_model().compute_score(
            [[query, candidate.data] for candidate in candidates],
            normalize=True,
        )
        if self.require_cuda and self._runtime is None:
            self._runtime = _inspect_cuda_model(self._get_model())
        if isinstance(raw_scores, (float, int)):
            scores = [float(raw_scores)]
        else:
            scores = [float(score) for score in raw_scores]
        if len(scores) != len(candidates):
            raise RuntimeError(
                "BGE returned a score count that does not match candidates"
            )

        ranked = sorted(
            zip(candidates, scores, strict=True),
            key=lambda item: item[1],
            reverse=True,
        )
        return [replace(candidate, score=score) for candidate, score in ranked[:limit]]

    def _get_model(self) -> BGEScoringModel:
        if self._model is None:
            if self.require_cuda:
                assert self.device is not None
                _require_cuda_device(self.device)
            if self._model_factory is not None:
                self._model = self._model_factory(self.model_name)
            else:
                self._model = _load_bge_model(
                    self.model_name,
                    use_fp16=self.use_fp16,
                    device=self.device,
                    batch_size=self.batch_size,
                    max_length=self.max_length,
                )
        return self._model

    @property
    def runtime(self) -> dict[str, Any]:
        """Return verified CUDA details after at least one strict rerank call."""
        if not self.require_cuda:
            return {}
        if self._runtime is None:
            raise RuntimeError("BGE CUDA runtime has not been verified by inference")
        return dict(self._runtime)
