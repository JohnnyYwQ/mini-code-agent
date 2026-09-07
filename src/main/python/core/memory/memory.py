from __future__ import annotations

import builtins
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol
from uuid import uuid4

from core.memory.extraction import (
    ExistingMemory,
    MemoryExtractor,
    MemoryMessage,
)
from core.memory.reranker import MemoryReranker
from core.memory.vector_store import MemorySearchResult, MemoryVectorStore


class DenseEncoder(Protocol):
    def encode_document(self, text: str) -> list[float]: ...

    def encode_query(self, text: str) -> list[float]: ...


@dataclass(frozen=True, slots=True)
class MemoryContext:
    """Trusted ownership and scope identifiers supplied by the caller."""

    user_id: str
    space_id: str

    def __post_init__(self) -> None:
        for field_name in ("user_id", "space_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must not be empty")
            object.__setattr__(self, field_name, value.strip())


class Memory:
    _RERANK_CANDIDATES_PER_SCOPE = 10

    def __init__(
        self,
        *,
        extractor: MemoryExtractor,
        dense_encoder: DenseEncoder,
        vector_store: MemoryVectorStore,
        reranker: MemoryReranker | None = None,
    ) -> None:
        self.extractor = extractor
        self.dense_encoder = dense_encoder
        self.vector_store = vector_store
        self.reranker = reranker

    def close(self) -> None:
        """Release resources owned by the configured vector-store adapter."""
        self.vector_store.close()

    def add(
        self,
        *,
        messages: Sequence[MemoryMessage],
        context: MemoryContext,
        prompt: str | None = None,
    ) -> builtins.list[str]:
        """Extract and store each current Memory as its own Qdrant Point.

        Writes are sequential and are not atomic. If a later write fails, an
        exception is raised and earlier Points remain stored.
        """
        space_filters: dict[str, str | int | bool | None] = {
            "user_id": context.user_id,
            "space_id": context.space_id,
        }
        query = "\n".join(
            f"{message['role']}: {message['content']}" for message in messages
        )
        user_results = self._search_scope(
            query=query,
            filters={"user_id": context.user_id, "space_id": None},
            limit=10,
        )
        space_results = self._search_scope(
            query=query,
            filters=space_filters,
            limit=10,
        )
        existing_results = self._reciprocal_rank_fusion(
            user_results,
            space_results,
            limit=10,
        )
        existing_memories = [
            ExistingMemory(
                reference=str(index),
                text=result.data,
                scope=result.scope,
            )
            for index, result in enumerate(existing_results)
        ]
        extracted_memories = self.extractor.extract(
            messages=messages,
            existing_memories=existing_memories,
            prompt=prompt,
        )
        memory_ids: builtins.list[str] = []

        for extracted_memory in extracted_memories:
            memory_hash = hashlib.md5(extracted_memory.text.encode()).hexdigest()
            dedupe_scope: dict[str, str | int | bool | None]
            payload_scope: dict[str, Any]
            if extracted_memory.target == "user":
                dedupe_scope = {
                    "user_id": context.user_id,
                    "space_id": None,
                }
                payload_scope = {"user_id": context.user_id}
            else:
                dedupe_scope = dict(space_filters)
                payload_scope = dict(space_filters)

            filters: dict[str, str | int | bool | None] = {
                **dedupe_scope,
                "hash": memory_hash,
            }
            if self.vector_store.exists(filters=filters):
                continue

            memory_id = str(uuid4())
            payload: dict[str, Any] = {
                "data": extracted_memory.text,
                **payload_scope,
                "hash": memory_hash,
            }

            self.vector_store.upsert(
                memory_id=memory_id,
                vector=self.dense_encoder.encode_document(extracted_memory.text),
                payload=payload,
            )
            memory_ids.append(memory_id)

        return memory_ids

    def _search_scope(
        self,
        *,
        query: str,
        filters: dict[str, str | int | bool | None],
        limit: int = 5,
    ) -> builtins.list[MemorySearchResult]:
        """Search one Scope derived internally from a trusted Memory Context."""
        if not filters:
            raise ValueError("filters must not be empty")

        dense_results = self.vector_store.dense_search(
            query_vector=self.dense_encoder.encode_query(query),
            top_k=limit,
            filters=filters,
        )
        keyword_results = self.vector_store.keyword_search(
            query=query,
            top_k=limit,
            filters=filters,
        )
        if keyword_results is None:
            return dense_results

        return self._reciprocal_rank_fusion(
            dense_results,
            keyword_results,
            limit=limit,
        )

    def recall(
        self,
        *,
        query: str,
        context: MemoryContext,
        limit: int = 5,
        rerank: bool = False,
    ) -> builtins.list[MemorySearchResult]:
        """Recall User and current Space Memories for one agent Turn."""
        scope_limit = self._RERANK_CANDIDATES_PER_SCOPE if rerank else limit
        user_results = self._search_scope(
            query=query,
            filters={"user_id": context.user_id, "space_id": None},
            limit=scope_limit,
        )
        space_results = self._search_scope(
            query=query,
            filters={
                "user_id": context.user_id,
                "space_id": context.space_id,
            },
            limit=scope_limit,
        )

        result_by_text: dict[str, MemorySearchResult] = {}
        score_by_text: dict[str, float] = {}
        for ranking in (user_results, space_results):
            for rank, result in enumerate(ranking, start=1):
                score_by_text[result.data] = score_by_text.get(
                    result.data,
                    0.0,
                ) + 1 / (60 + rank)
                selected = result_by_text.get(result.data)
                if selected is None or (
                    result.scope == "user" and selected.scope != "user"
                ):
                    result_by_text[result.data] = result

        ranked_texts = sorted(
            score_by_text,
            key=score_by_text.__getitem__,
            reverse=True,
        )[: scope_limit * 2]
        candidates = [
            replace(result_by_text[text], score=score_by_text[text])
            for text in ranked_texts
        ]
        if not rerank:
            return candidates[:limit]
        if self.reranker is None:
            raise RuntimeError("rerank=True requires a configured MemoryReranker")
        return self.reranker.rerank(
            query=query,
            candidates=candidates,
            limit=limit,
        )

    def _reciprocal_rank_fusion(
        self,
        *rankings: builtins.list[MemorySearchResult],
        limit: int,
    ) -> builtins.list[MemorySearchResult]:
        points_by_id: dict[str, MemorySearchResult] = {}
        scores_by_id: dict[str, float] = {}
        for ranking in rankings:
            for rank, point in enumerate(ranking, start=1):
                points_by_id.setdefault(point.id, point)
                scores_by_id[point.id] = scores_by_id.get(point.id, 0.0) + 1 / (
                    60 + rank
                )

        ranked_ids = sorted(
            scores_by_id,
            key=scores_by_id.__getitem__,
            reverse=True,
        )[:limit]
        return [
            replace(points_by_id[point_id], score=scores_by_id[point_id])
            for point_id in ranked_ids
        ]
