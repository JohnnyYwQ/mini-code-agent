from dataclasses import dataclass
from typing import Any, Literal, Protocol


@dataclass(frozen=True, slots=True)
class MemorySearchResult:
    id: str
    data: str
    scope: Literal["user", "space"]
    score: float
    metadata: dict[str, Any]


class MemoryVectorStore(Protocol):
    def close(self) -> None: ...

    def exists(
        self,
        *,
        filters: dict[str, str | int | bool | None],
    ) -> bool: ...

    def upsert(
        self,
        *,
        memory_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None: ...

    def dense_search(
        self,
        *,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, str | int | bool | None],
    ) -> list[MemorySearchResult]: ...

    def keyword_search(
        self,
        *,
        query: str,
        top_k: int,
        filters: dict[str, str | int | bool | None],
    ) -> list[MemorySearchResult] | None: ...
