from unittest import TestCase
from uuid import uuid4

from core.memory.extraction import ExtractedMemory
from core.memory.memory import Memory, MemoryContext
from core.memory.qdrant_store import QdrantStore
from qdrant_client import QdrantClient


class FakeMemoryExtractor:
    def __init__(self, extracted_memories):
        self.extracted_memories = extracted_memories

    def extract(self, *, messages, existing_memories, prompt=None):
        return self.extracted_memories


class SpaceScopeAwareExtractor:
    def extract(self, *, messages, existing_memories, prompt=None):
        if any(
            memory.text == "This project uses Django." and memory.scope == "space"
            for memory in existing_memories
        ):
            return []
        return [
            ExtractedMemory(
                text="This project uses the Django framework.",
                target="space",
            )
        ]


class VisibleScopesAwareExtractor:
    def extract(self, *, messages, existing_memories, prompt=None):
        visible_memories = {(memory.text, memory.scope) for memory in existing_memories}
        if visible_memories == {
            ("User prefers concise responses.", "user"),
            ("This project uses Django.", "space"),
        }:
            return []
        return [
            ExtractedMemory(
                text="The visible Memory Scopes were incomplete.",
                target="space",
            )
        ]


class PromptAwareExtractor:
    def extract(self, *, messages, existing_memories, prompt):
        if prompt != "Extract only stable user preferences.":
            return []
        return [
            ExtractedMemory(
                text="User prefers concise responses.",
                target="user",
            )
        ]


class FakeDenseEncoder:
    def encode_document(self, text):
        return [1.0, 0.0, 0.0]

    def encode_query(self, text):
        return [1.0, 0.0, 0.0]


class MemoryAddTests(TestCase):
    def test_adds_and_deduplicates_user_target_in_user_scope(self):
        client = QdrantClient(":memory:")
        store = QdrantStore(
            client=client,
            collection_name="test_memory_add_user_target",
            dimension=3,
        )
        memory_text = "User prefers concise responses."
        memory = Memory(
            extractor=FakeMemoryExtractor(
                [ExtractedMemory(text=memory_text, target="user")]
            ),
            dense_encoder=FakeDenseEncoder(),
            vector_store=store,
        )
        context = MemoryContext(
            user_id="user-123",
            space_id="space-456",
        )
        messages = [
            {
                "role": "user",
                "content": "Please keep your responses concise.",
            },
        ]

        try:
            first_memory_ids = memory.add(messages=messages, context=context)
            duplicate_memory_ids = memory.add(messages=messages, context=context)
            visible_results = memory.recall(
                query=memory_text,
                context=context,
            )

            self.assertEqual(len(first_memory_ids), 1)
            self.assertEqual(duplicate_memory_ids, [])
            self.assertEqual(
                [(result.id, result.data, result.scope) for result in visible_results],
                [(first_memory_ids[0], memory_text, "user")],
            )
        finally:
            client.close()

    def test_supplies_user_and_current_space_memories_to_extractor(self):
        client = QdrantClient(":memory:")
        store = QdrantStore(
            client=client,
            collection_name="test_memory_add_visible_scopes",
            dimension=3,
        )
        memories = [
            (
                "User prefers concise responses.",
                {"user_id": "user-123"},
            ),
            (
                "This project uses Django.",
                {"user_id": "user-123", "space_id": "space-456"},
            ),
            (
                "Another project uses Flask.",
                {"user_id": "user-123", "space_id": "space-other"},
            ),
            (
                "Another user prefers verbose responses.",
                {"user_id": "user-other"},
            ),
        ]
        for text, scope_payload in memories:
            store.upsert(
                memory_id=str(uuid4()),
                vector=[1.0, 0.0, 0.0],
                payload={"data": text, **scope_payload},
            )

        memory = Memory(
            extractor=VisibleScopesAwareExtractor(),
            dense_encoder=FakeDenseEncoder(),
            vector_store=store,
        )

        try:
            memory_ids = memory.add(
                messages=[
                    {
                        "role": "user",
                        "content": "Please keep this Django project concise.",
                    },
                ],
                context=MemoryContext(
                    user_id="user-123",
                    space_id="space-456",
                ),
            )

            self.assertEqual(memory_ids, [])
        finally:
            client.close()

    def test_supplies_space_scope_for_existing_space_memory(self):
        client = QdrantClient(":memory:")
        store = QdrantStore(
            client=client,
            collection_name="test_memory_add_existing_space_scope",
            dimension=3,
        )
        store.upsert(
            memory_id=str(uuid4()),
            vector=[1.0, 0.0, 0.0],
            payload={
                "data": "This project uses Django.",
                "user_id": "user-123",
                "space_id": "space-456",
            },
        )
        memory = Memory(
            extractor=SpaceScopeAwareExtractor(),
            dense_encoder=FakeDenseEncoder(),
            vector_store=store,
        )

        try:
            memory_ids = memory.add(
                messages=[
                    {
                        "role": "user",
                        "content": "This project is built with Django.",
                    },
                ],
                context=MemoryContext(
                    user_id="user-123",
                    space_id="space-456",
                ),
            )

            self.assertEqual(memory_ids, [])
        finally:
            client.close()

    def test_makes_an_extracted_space_memory_searchable(self):
        client = QdrantClient(":memory:")
        store = QdrantStore(
            client=client,
            collection_name="test_memory_add",
            dimension=3,
        )
        memory_text = (
            "User generally prefers concise responses, but wants "
            "step-by-step explanations when learning code."
        )
        extractor = FakeMemoryExtractor(
            [
                ExtractedMemory(
                    text=memory_text,
                    target="space",
                )
            ]
        )
        memory = Memory(
            extractor=extractor,
            dense_encoder=FakeDenseEncoder(),
            vector_store=store,
        )
        messages = [
            {
                "role": "user",
                "content": "以后回答简短点，但我学习代码时请一步一步解释。",
            },
        ]

        try:
            memory_ids = memory.add(
                messages=messages,
                context=MemoryContext(
                    user_id="user-123",
                    space_id="space-456",
                ),
            )

            self.assertEqual(len(memory_ids), 1)
            results = memory.recall(
                query=memory_text,
                context=MemoryContext(
                    user_id="user-123",
                    space_id="space-456",
                ),
            )
            self.assertEqual(
                [(result.id, result.data, result.scope) for result in results],
                [(memory_ids[0], memory_text, "space")],
            )
        finally:
            client.close()

    def test_does_not_add_the_same_memory_twice_within_one_scope(self):
        client = QdrantClient(":memory:")
        store = QdrantStore(
            client=client,
            collection_name="test_memory_add_exact_duplicate",
            dimension=3,
        )
        extractor = FakeMemoryExtractor(
            [
                ExtractedMemory(
                    text="User prefers step-by-step explanations when learning code.",
                    target="space",
                )
            ]
        )
        memory = Memory(
            extractor=extractor,
            dense_encoder=FakeDenseEncoder(),
            vector_store=store,
        )
        messages = [
            {
                "role": "user",
                "content": "我学习代码时，请一步一步解释。",
            },
        ]
        context = MemoryContext(
            user_id="user-123",
            space_id="space-456",
        )

        try:
            first_memory_ids = memory.add(messages=messages, context=context)
            duplicate_memory_ids = memory.add(messages=messages, context=context)

            self.assertEqual(len(first_memory_ids), 1)
            self.assertEqual(duplicate_memory_ids, [])
        finally:
            client.close()

    def test_adds_the_same_memory_to_a_different_space(self):
        client = QdrantClient(":memory:")
        store = QdrantStore(
            client=client,
            collection_name="test_memory_add_different_space",
            dimension=3,
        )
        extractor = FakeMemoryExtractor(
            [
                ExtractedMemory(
                    text="User prefers step-by-step explanations when learning code.",
                    target="space",
                )
            ]
        )
        memory = Memory(
            extractor=extractor,
            dense_encoder=FakeDenseEncoder(),
            vector_store=store,
        )
        messages = [
            {
                "role": "user",
                "content": "我学习代码时，请一步一步解释。",
            },
        ]

        try:
            first_space_ids = memory.add(
                messages=messages,
                context=MemoryContext(
                    user_id="user-123",
                    space_id="space-1",
                ),
            )
            second_space_ids = memory.add(
                messages=messages,
                context=MemoryContext(
                    user_id="user-123",
                    space_id="space-2",
                ),
            )

            self.assertEqual(len(first_space_ids), 1)
            self.assertEqual(len(second_space_ids), 1)
            self.assertNotEqual(first_space_ids, second_space_ids)
        finally:
            client.close()

    def test_applies_a_custom_extraction_prompt(self):
        client = QdrantClient(":memory:")
        store = QdrantStore(
            client=client,
            collection_name="test_memory_add_custom_prompt",
            dimension=3,
        )
        memory = Memory(
            extractor=PromptAwareExtractor(),
            dense_encoder=FakeDenseEncoder(),
            vector_store=store,
        )

        try:
            memory_ids = memory.add(
                messages=[
                    {
                        "role": "user",
                        "content": "Please keep your answers brief.",
                    },
                ],
                context=MemoryContext(
                    user_id="user-123",
                    space_id="space-456",
                ),
                prompt="Extract only stable user preferences.",
            )

            self.assertEqual(len(memory_ids), 1)
        finally:
            client.close()
