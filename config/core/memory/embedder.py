from collections.abc import Callable, Iterable
from typing import Any

from qdrant_client import models


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
        bm25_text = self._prepare_text(text)
        embeddings = self.model.embed([bm25_text])
        return self._to_sparse_vector(embeddings)

    def encode_query(self, text: str) -> models.SparseVector:
        """Encode search text with BM25 query weighting."""
        bm25_text = self._prepare_text(text)
        embeddings = self.model.query_embed([bm25_text])
        return self._to_sparse_vector(embeddings)

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
