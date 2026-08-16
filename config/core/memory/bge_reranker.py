from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Protocol

from core.memory.vector_store import MemorySearchResult

DEFAULT_BGE_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"


class BGEScoringModel(Protocol):
    def compute_score(
        self,
        sentence_pairs: list[list[str]],
        *,
        normalize: bool,
    ) -> Sequence[float] | float: ...


def _load_bge_model(model_name: str) -> BGEScoringModel:
    from FlagEmbedding import FlagReranker  # type: ignore[import-untyped]

    return FlagReranker(model_name, use_fp16=False)


class BGEReranker:
    """Lazily load BGE and rerank Memory retrieval candidates."""

    def __init__(
        self,
        model_name: str = DEFAULT_BGE_RERANKER_MODEL,
        *,
        model_factory: Callable[[str], BGEScoringModel] = _load_bge_model,
    ) -> None:
        self.model_name = model_name
        self._model_factory = model_factory
        self._model: BGEScoringModel | None = None

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
            self._model = self._model_factory(self.model_name)
        return self._model
