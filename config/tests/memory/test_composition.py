from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from core.memory.composition import MemoryCompositionConfig, build_memory
from core.memory.config import AnthropicLLMConfig
from core.memory.extraction import LLMMemoryExtractor
from core.memory.qdrant_store import QdrantStore


class MemoryCompositionTests(TestCase):
    @patch("core.memory.composition.SparseTextEmbedding", return_value=object())
    @patch("core.memory.composition.build_multilingual_e5_base_encoder")
    def test_builds_memory_with_persistent_adapter_seams(
        self,
        build_dense_encoder,
        sparse_embedding,
    ):
        dense_encoder = object()
        build_dense_encoder.return_value = dense_encoder

        memory = build_memory(
            config=MemoryCompositionConfig(
                llm=AnthropicLLMConfig(
                    api_key="test-key",
                    model="test-model",
                    max_tokens=100,
                ),
                qdrant_location=":memory:",
                collection_name="composition_test",
            )
        )

        try:
            self.assertIs(memory.dense_encoder, dense_encoder)
            self.assertIsInstance(memory.extractor, LLMMemoryExtractor)
            self.assertIsInstance(memory.vector_store, QdrantStore)
        finally:
            memory.close()

    @patch("core.memory.composition.SparseTextEmbedding", return_value=object())
    @patch("core.memory.composition.build_multilingual_e5_base_encoder")
    def test_builds_memory_with_persistent_local_path(
        self,
        build_dense_encoder,
        sparse_embedding,
    ):
        build_dense_encoder.return_value = object()

        with TemporaryDirectory() as qdrant_path:
            memory = build_memory(
                config=MemoryCompositionConfig(
                    llm=AnthropicLLMConfig(
                        api_key="test-key",
                        model="test-model",
                        max_tokens=100,
                    ),
                    qdrant_location=qdrant_path,
                    collection_name="persistent_composition_test",
                )
            )

            try:
                self.assertIsInstance(memory.vector_store, QdrantStore)
            finally:
                memory.close()
