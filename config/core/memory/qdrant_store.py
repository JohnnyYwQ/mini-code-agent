import logging
from typing import Any, Protocol

from qdrant_client import QdrantClient, models

from core.memory.vector_store import MemorySearchResult

logger = logging.getLogger(__name__)


def _build_query_filter(
    filters: dict[str, str | int | bool | None] | None,
) -> models.Filter | None:
    if not filters:
        return None

    conditions: list[models.Condition] = []
    for key, value in filters.items():
        if value is None:
            conditions.append(
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key=key),
                )
            )
        else:
            conditions.append(
                models.FieldCondition(
                    key=key,
                    match=models.MatchValue(value=value),
                )
            )

    return models.Filter(must=conditions)


def _to_memory_search_result(point: models.ScoredPoint) -> MemorySearchResult:
    payload = dict(point.payload or {})
    data = payload.pop("data", "")
    payload.pop("hash", None)
    return MemorySearchResult(
        id=str(point.id),
        data=data,
        scope="space" if "space_id" in payload else "user",
        score=point.score,
        metadata=payload,
    )


class BM25Encoder(Protocol):
    def encode_document(self, text: str) -> models.SparseVector | None: ...

    def encode_query(self, text: str) -> models.SparseVector | None: ...


class QdrantStore:
    """Store memory vectors in a Qdrant collection."""

    def __init__(
        self,
        *,
        client: QdrantClient,
        collection_name: str,
        dimension: int,
        bm25_encoder: BM25Encoder | None = None,
    ) -> None:
        if not collection_name:
            raise ValueError("collection_name must not be empty")
        if dimension <= 0:
            raise ValueError("dimension must be greater than zero")

        self.client = client
        self.collection_name = collection_name
        self.dimension = dimension
        self.bm25_encoder = bm25_encoder
        self._has_bm25_slot = False
        self._ensure_collection()

    def close(self) -> None:
        self.client.close()

    def upsert(
        self,
        *,
        memory_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None:
        if len(vector) != self.dimension:
            raise ValueError(
                f"vector dimension {len(vector)}, expected {self.dimension}"
            )

        point_vectors: dict[str, models.Vector] = {"": vector}
        text = payload.get("data")
        if (
            self._has_bm25_slot
            and self.bm25_encoder is not None
            and isinstance(text, str)
            and text
        ):
            try:
                bm25_vector = self.bm25_encoder.encode_document(text)
            except Exception:
                logger.warning(
                    "BM25 encoding failed; storing dense vector only",
                    exc_info=True,
                )
                bm25_vector = None
            if bm25_vector is not None:
                point_vectors["bm25"] = bm25_vector

        point = models.PointStruct(
            id=memory_id,
            vector=point_vectors,
            payload=payload,
        )
        self.client.upsert(
            collection_name=self.collection_name,
            points=[point],
            wait=True,
        )

    def exists(
        self,
        *,
        filters: dict[str, str | int | bool | None],
    ) -> bool:
        result = self.client.count(
            collection_name=self.collection_name,
            count_filter=_build_query_filter(filters),
            exact=True,
        )
        return result.count > 0

    def dense_search(
        self,
        *,
        query_vector: list[float],
        top_k: int = 5,
        filters: dict[str, str | int | bool | None] | None = None,
    ) -> list[MemorySearchResult]:
        if len(query_vector) != self.dimension:
            raise ValueError(
                f"query vector dimension {len(query_vector)}, expected {self.dimension}"
            )

        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=_build_query_filter(filters),
            limit=top_k,
        )
        return [_to_memory_search_result(point) for point in response.points]

    def keyword_search(
        self,
        *,
        query: str,
        top_k: int = 5,
        filters: dict[str, str | int | bool | None] | None = None,
    ) -> list[MemorySearchResult] | None:
        if not self._has_bm25_slot or self.bm25_encoder is None:
            return None

        try:
            sparse_query = self.bm25_encoder.encode_query(query)
        except Exception:
            logger.warning(
                "BM25 query encoding failed; keyword search unavailable",
                exc_info=True,
            )
            return None
        if sparse_query is None:
            return None

        response = self.client.query_points(
            collection_name=self.collection_name,
            query=sparse_query,
            using="bm25",
            query_filter=_build_query_filter(filters),
            limit=top_k,
        )
        return [_to_memory_search_result(point) for point in response.points]

    def _ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection_name):
            collection = self.client.get_collection(self.collection_name)
            self._validate_dense_vector_config(collection.config.params.vectors)
            sparse_vectors = collection.config.params.sparse_vectors
            self._has_bm25_slot = bool(sparse_vectors and "bm25" in sparse_vectors)
            return

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=self.dimension,
                distance=models.Distance.COSINE,
            ),
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF),
            },
        )
        self._has_bm25_slot = True

    def _validate_dense_vector_config(
        self,
        vectors: models.VectorParams | dict[str, models.VectorParams] | None,
    ) -> None:
        if not isinstance(vectors, models.VectorParams):
            raise ValueError(
                f"Collection '{self.collection_name}' must use one unnamed dense vector"
            )

        if vectors.size != self.dimension:
            raise ValueError(
                f"Collection '{self.collection_name}' has dense vector dimension "
                f"{vectors.size}, expected {self.dimension}"
            )

        if vectors.distance != models.Distance.COSINE:
            raise ValueError(
                f"Collection '{self.collection_name}' has distance "
                f"{vectors.distance}, expected {models.Distance.COSINE}"
            )
