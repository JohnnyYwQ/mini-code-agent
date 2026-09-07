from unittest import TestCase

from core.memory import extraction as memory_extraction
from core.memory import llm as memory_llm
from core.memory.extraction import ExistingMemory, LLMMemoryExtractor


class FakeLLM:
    def __init__(self):
        self.messages = None

    def generate_response(self, *, messages):
        self.messages = list(messages)
        return """{
            "memory": [
                {"text": "User prefers concise responses.", "target": "user"},
                {"text": "User is learning Python.", "target": "space"}
            ]
        }"""


class InvalidResponseLLM:
    def generate_response(self, *, messages):
        return "This is not JSON."


class InvalidSchemaLLM:
    def generate_response(self, *, messages):
        return '{"memory": [{"wrong_field": "value"}]}'


class InvalidTargetLLM:
    def generate_response(self, *, messages):
        return """{
            "memory": [
                {"text": "User prefers concise responses.", "target": "user"},
                {"text": "User is learning Python.", "target": "project"}
            ]
        }"""


class FailingLLM:
    def generate_response(self, *, messages):
        raise memory_llm.LLMError("LLM provider request failed")


class LLMMemoryExtractorTests(TestCase):
    def test_returns_extracted_memories_with_targets_from_llm_response(self):
        extractor = LLMMemoryExtractor(llm=FakeLLM())

        extracted_memories = extractor.extract(
            messages=[
                {
                    "role": "user",
                    "content": "请简短回答；我正在学习 Python。",
                },
            ],
            existing_memories=[],
            prompt="Extract only stable user facts and preferences.",
        )

        self.assertEqual(
            [(memory.text, memory.target) for memory in extracted_memories],
            [
                ("User prefers concise responses.", "user"),
                ("User is learning Python.", "space"),
            ],
        )

    def test_supplies_extraction_context_to_llm(self):
        llm = FakeLLM()
        extractor = LLMMemoryExtractor(llm=llm)

        extractor.extract(
            messages=[
                {
                    "role": "user",
                    "content": "我正在学习 Python。",
                },
            ],
            existing_memories=[
                ExistingMemory(
                    reference="0",
                    text="User prefers dark mode.",
                    scope="user",
                ),
            ],
            prompt="Extract only stable user facts.",
        )

        self.assertIsNotNone(llm.messages)
        self.assertEqual(
            [message["role"] for message in llm.messages],
            ["system", "user"],
        )
        self.assertTrue(llm.messages[0]["content"].strip())

        user_prompt = llm.messages[1]["content"]
        self.assertIn("User prefers dark mode.", user_prompt)
        self.assertIn('"reference": "0"', user_prompt)
        self.assertIn('"scope": "user"', user_prompt)
        self.assertIn("我正在学习 Python。", user_prompt)
        self.assertIn("Extract only stable user facts.", user_prompt)

    def test_tells_llm_how_to_choose_each_memory_target(self):
        llm = FakeLLM()
        extractor = LLMMemoryExtractor(llm=llm)

        extractor.extract(
            messages=[
                {
                    "role": "user",
                    "content": "请记住我喜欢简短回答。",
                },
            ],
            existing_memories=[],
        )

        self.assertIsNotNone(llm.messages)
        system_prompt = llm.messages[0]["content"]
        self.assertIn('"target": "user"', system_prompt)
        self.assertIn('"target": "space"', system_prompt)
        self.assertIn("across all Memory Spaces", system_prompt)
        self.assertIn("current Memory Space", system_prompt)
        self.assertIn("newer explicit statements", system_prompt)
        self.assertIn("supersede or contradict", system_prompt)

    def test_raises_memory_extraction_error_for_invalid_llm_response(self):
        extractor = LLMMemoryExtractor(llm=InvalidResponseLLM())

        with self.assertRaises(memory_extraction.MemoryExtractionError) as caught_error:
            extractor.extract(
                messages=[
                    {
                        "role": "user",
                        "content": "请记住我喜欢简短回答。",
                    },
                ],
                existing_memories=[],
            )

        error_message = str(caught_error.exception)
        self.assertEqual(
            type(caught_error.exception.__cause__).__name__,
            "JSONDecodeError",
        )
        self.assertIn("This is not JSON.", error_message)

    def test_raises_memory_extraction_error_for_invalid_response_schema(self):
        extractor = LLMMemoryExtractor(llm=InvalidSchemaLLM())

        with self.assertRaises(memory_extraction.MemoryExtractionError):
            extractor.extract(
                messages=[
                    {
                        "role": "user",
                        "content": "请记住我喜欢简短回答。",
                    },
                ],
                existing_memories=[],
            )

    def test_rejects_entire_response_when_any_memory_has_invalid_target(self):
        extractor = LLMMemoryExtractor(llm=InvalidTargetLLM())

        with self.assertRaises(memory_extraction.MemoryExtractionError):
            extractor.extract(
                messages=[
                    {
                        "role": "user",
                        "content": "请简短回答；我正在学习 Python。",
                    },
                ],
                existing_memories=[],
            )

    def test_raises_memory_extraction_error_when_llm_fails(self):
        extractor = LLMMemoryExtractor(llm=FailingLLM())

        with self.assertRaises(memory_extraction.MemoryExtractionError):
            extractor.extract(
                messages=[
                    {
                        "role": "user",
                        "content": "请记住我喜欢简短回答。",
                    },
                ],
                existing_memories=[],
            )
