from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, cast

from core.memory.vector_store import MemorySearchResult

DEFAULT_FLASHRANK_MODEL = "ms-marco-MultiBERT-L-12"
DEFAULT_FLASHRANK_CACHE_DIR = Path.home() / ".mini-code-agent" / "models" / "flashrank"


class FlashRankBackend(Protocol):
    def __call__(
        self,
        *,
        query: str,
        passages: list[dict[str, object]],
    ) -> Sequence[Mapping[str, object]]: ...


def _load_flashrank_backend(
    model_name: str,
    cache_dir: Path,
) -> FlashRankBackend:
    flashrank = import_module("flashrank")
    ranker = flashrank.Ranker(model_name=model_name, cache_dir=str(cache_dir))

    def rerank(
        *,
        query: str,
        passages: list[dict[str, object]],
    ) -> Sequence[Mapping[str, object]]:
        request = flashrank.RerankRequest(query=query, passages=passages)
        return cast(Sequence[Mapping[str, object]], ranker.rerank(request))

    return rerank


class FlashRankReranker:
    """Lazily load FlashRank and rerank Memory retrieval candidates."""

    def __init__(
        self,
        model_name: str = DEFAULT_FLASHRANK_MODEL,
        *,
        cache_dir: Path = DEFAULT_FLASHRANK_CACHE_DIR,
        backend_factory: Callable[[str, Path], FlashRankBackend] = (
            _load_flashrank_backend
        ),
    ) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._backend_factory = backend_factory
        self._backend: FlashRankBackend | None = None

    def rerank(
        self,
        *,
        query: str,
        candidates: Sequence[MemorySearchResult],
        limit: int,
    ) -> list[MemorySearchResult]:
        if limit <= 0 or not candidates:
            return []

        raw_results = self._get_backend()(
            query=query,
            passages=[
                {"id": index, "text": candidate.data}
                for index, candidate in enumerate(candidates)
            ],
        )
        if len(raw_results) != len(candidates):
            raise RuntimeError(
                "FlashRank returned a result count that does not match candidates"
            )

        try:
            ranked = [
                replace(
                    candidates[int(cast(Any, result["id"]))],
                    score=float(cast(Any, result["score"])),
                )
                for result in raw_results
            ]
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise RuntimeError("FlashRank returned an invalid result") from error
        return ranked[:limit]

    def _get_backend(self) -> FlashRankBackend:
        if self._backend is None:
            self._backend = self._backend_factory(
                self.model_name,
                self.cache_dir,
            )
        return self._backend
