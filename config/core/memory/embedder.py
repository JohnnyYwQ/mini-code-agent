from collections.abc import Callable, Iterable
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

    def _encode(self, text: str) -> list[float]:
        embedding = next(iter(self.model.embed([text])))
        return list(embedding.tolist())


def build_multilingual_e5_base_encoder() -> FastEmbedE5Encoder:
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

    model = TextEmbedding(model_name=MULTILINGUAL_E5_BASE_MODEL)
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
