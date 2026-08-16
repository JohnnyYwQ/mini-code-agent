from collections.abc import Sequence
from typing import Protocol

from core.memory.vector_store import MemorySearchResult


class MemoryReranker(Protocol):
    """Reorder retrieval candidates and return at most ``limit`` results."""

    def rerank(
        self,
        *,
        query: str,
        candidates: Sequence[MemorySearchResult],
        limit: int,
    ) -> list[MemorySearchResult]: ...
