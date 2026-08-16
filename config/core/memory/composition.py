"""Production composition for the Memory module."""

import logging
from dataclasses import dataclass

import jieba  # type: ignore[import-untyped]
from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient

from core.memory.config import AnthropicLLMConfig
from core.memory.embedder import (
    MULTILINGUAL_E5_BASE_DIMENSION,
    FastEmbedBM25Encoder,
    build_multilingual_e5_base_encoder,
)
from core.memory.extraction import LLMMemoryExtractor
from core.memory.llm import AnthropicLLM
from core.memory.memory import Memory
from core.memory.qdrant_store import QdrantStore


@dataclass(frozen=True, slots=True)
class MemoryCompositionConfig:
    llm: AnthropicLLMConfig
    qdrant_location: str
    collection_name: str = "mini_code_agent_memories"
    bm25_model: str = "Qdrant/bm25"

    def __post_init__(self) -> None:
        if not self.qdrant_location:
            raise ValueError("qdrant_location must not be empty")
        if not self.collection_name:
            raise ValueError("collection_name must not be empty")
        if not self.bm25_model:
            raise ValueError("bm25_model must not be empty")


def _build_qdrant_client(location: str) -> QdrantClient:
    if location == ":memory:":
        return QdrantClient(location=location)
    if "://" in location:
        return QdrantClient(url=location)
    return QdrantClient(path=location)


def build_memory(*, config: MemoryCompositionConfig) -> Memory:
    """Assemble reusable production adapters behind the Memory interface."""
    jieba.setLogLevel(logging.WARNING)
    dense_encoder = build_multilingual_e5_base_encoder()
    bm25_encoder = FastEmbedBM25Encoder(
        model=SparseTextEmbedding(model_name=config.bm25_model),
        chinese_segmenter=jieba.cut,
    )
    vector_store = QdrantStore(
        client=_build_qdrant_client(config.qdrant_location),
        collection_name=config.collection_name,
        dimension=MULTILINGUAL_E5_BASE_DIMENSION,
        bm25_encoder=bm25_encoder,
    )
    extractor = LLMMemoryExtractor(llm=AnthropicLLM(config=config.llm))
    return Memory(
        extractor=extractor,
        dense_encoder=dense_encoder,
        vector_store=vector_store,
    )
