from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from core.memory.memory import MemoryContext
from django.contrib.auth import get_user_model
from django.test import TestCase

from chat.application import (
    AgentResponseError,
    ConversationNotFoundError,
    ConversationRuntimeContext,
    WorkspaceUnavailableError,
    append_conversation_message,
    append_conversation_messages,
    list_conversations,
    load_conversation_messages,
    require_available_workspace,
    resolve_memory_context,
    resolve_workspace_path,
    resume_conversation,
    run_conversation_turn,
    start_conversation,
)


class StartConversationTests(TestCase):
    def test_starts_conversation_in_workspace_memory_space(self):
        with TemporaryDirectory() as workspace:
            conversation = start_conversation(workspace_path=Path(workspace))

            self.assertEqual(
                conversation.memory_space.workspace_path,
                str(Path(workspace).resolve()),
            )

    def test_normalizes_reserved_local_user_to_unusable_password(self):
        local_user = get_user_model().objects.create_user(
            username="local",
            password="temporary-password",
        )

        with TemporaryDirectory() as workspace:
            conversation = start_conversation(workspace_path=Path(workspace))

        local_user.refresh_from_db()
        self.assertFalse(local_user.has_usable_password())
        self.assertEqual(conversation.memory_space.owner_id, local_user.id)


class ResolveMemoryContextTests(TestCase):
    def test_resolves_context_from_conversation_ownership(self):
        with TemporaryDirectory() as workspace:
            conversation = start_conversation(workspace_path=Path(workspace))

        self.assertEqual(
            resolve_memory_context(conversation_id=conversation.id),
            MemoryContext(
                user_id=str(conversation.memory_space.owner_id),
                space_id=str(conversation.memory_space_id),
            ),
        )

    def test_rejects_missing_conversation(self):
        with self.assertRaises(ConversationNotFoundError):
            resolve_memory_context(conversation_id=uuid4())


class ResolveWorkspacePathTests(TestCase):
    def test_resolves_workspace_from_conversation(self):
        with TemporaryDirectory() as workspace:
            conversation = start_conversation(workspace_path=Path(workspace))

            self.assertEqual(
                resolve_workspace_path(conversation_id=conversation.id),
                Path(workspace).resolve(),
            )


class RequireAvailableWorkspaceTests(TestCase):
    def test_rejects_conversation_when_workspace_is_missing(self):
        with TemporaryDirectory() as workspace:
            conversation = start_conversation(workspace_path=Path(workspace))

        with self.assertRaises(WorkspaceUnavailableError):
            require_available_workspace(conversation_id=conversation.id)


class ConversationTranscriptTests(TestCase):
    def test_appended_message_can_be_loaded_with_complete_content(self):
        with TemporaryDirectory() as workspace:
            conversation = start_conversation(workspace_path=Path(workspace))

        message = {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "I will inspect the file."},
                {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "read",
                    "input": {"path": "README.md"},
                },
            ],
        }

        append_conversation_message(
            conversation_id=conversation.id,
            message=message,
        )

        self.assertEqual(
            load_conversation_messages(conversation_id=conversation.id),
            [message],
        )

    def test_appends_generated_messages_as_one_ordered_batch(self):
        with TemporaryDirectory() as workspace:
            conversation = start_conversation(workspace_path=Path(workspace))

        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "read",
                        "input": {"path": "README.md"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": "README contents",
                    }
                ],
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Finished."}],
            },
        ]

        append_conversation_messages(
            conversation_id=conversation.id,
            messages=messages,
        )

        self.assertEqual(
            load_conversation_messages(conversation_id=conversation.id),
            messages,
        )


class ConversationListingTests(TestCase):
    def test_first_user_query_names_conversation_in_its_workspace(self):
        with TemporaryDirectory() as workspace:
            workspace_path = Path(workspace)
            conversation = start_conversation(workspace_path=workspace_path)

            append_conversation_message(
                conversation_id=conversation.id,
                message={"role": "user", "content": "Explain this repository"},
            )
            append_conversation_message(
                conversation_id=conversation.id,
                message={"role": "user", "content": "Do not rename it"},
            )

            summaries = list_conversations(workspace_path=workspace_path)

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].title, "Explain this repository")
        self.assertEqual(summaries[0].workspace_path, workspace_path.resolve())

    def test_cli_resume_is_limited_to_launch_workspace(self):
        with (
            TemporaryDirectory() as first_workspace,
            TemporaryDirectory() as second_workspace,
        ):
            conversation = start_conversation(workspace_path=Path(first_workspace))

            resumed = resume_conversation(
                conversation_id=conversation.id,
                workspace_path=Path(first_workspace),
            )
            with self.assertRaises(ConversationNotFoundError):
                resume_conversation(
                    conversation_id=conversation.id,
                    workspace_path=Path(second_workspace),
                )

        self.assertEqual(resumed.id, conversation.id)


class RunConversationTurnTests(TestCase):
    def test_persists_user_before_run_and_generated_messages_after_success(self):
        with TemporaryDirectory() as workspace:
            workspace_path = Path(workspace)
            conversation = start_conversation(workspace_path=workspace_path)
            observed_messages = []
            observed_contexts = []

            class FakeRunner:
                def run(self, *, messages, latest_user_query):
                    observed_messages.extend(messages)
                    return [
                        {
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Hello."}],
                        }
                    ]

            def runner_factory(context: ConversationRuntimeContext):
                observed_contexts.append(context)
                return FakeRunner()

            result = run_conversation_turn(
                conversation_id=conversation.id,
                query="Hello",
                runner_factory=runner_factory,
            )

        self.assertEqual(
            observed_messages,
            [{"role": "user", "content": "Hello"}],
        )
        self.assertEqual(observed_contexts[0].workspace_path, workspace_path.resolve())
        self.assertEqual(result.assistant_text, "Hello.")
        self.assertEqual(
            load_conversation_messages(conversation_id=conversation.id),
            [
                {"role": "user", "content": "Hello"},
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hello."}],
                },
            ],
        )

    def test_leaves_only_user_message_when_agent_fails(self):
        with TemporaryDirectory() as workspace:
            conversation = start_conversation(workspace_path=Path(workspace))

            class FailingRunner:
                def run(self, *, messages, latest_user_query):
                    raise RuntimeError("model failed")

            with self.assertRaisesRegex(RuntimeError, "model failed"):
                run_conversation_turn(
                    conversation_id=conversation.id,
                    query="Keep this question",
                    runner_factory=lambda context: FailingRunner(),
                )

        self.assertEqual(
            load_conversation_messages(conversation_id=conversation.id),
            [{"role": "user", "content": "Keep this question"}],
        )

    def test_rejects_tool_preamble_when_final_assistant_reply_is_empty(self):
        with TemporaryDirectory() as workspace:
            conversation = start_conversation(workspace_path=Path(workspace))

            class EmptyFinalReplyRunner:
                def run(self, *, messages, latest_user_query):
                    return [
                        {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "I will inspect it."},
                                {
                                    "type": "tool_use",
                                    "id": "tool-1",
                                    "name": "read_file",
                                    "input": {"path": "README.md"},
                                },
                            ],
                        },
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "tool-1",
                                    "content": "README contents",
                                }
                            ],
                        },
                        {"role": "assistant", "content": []},
                    ]

            with self.assertRaisesRegex(
                AgentResponseError,
                "no assistant text",
            ):
                run_conversation_turn(
                    conversation_id=conversation.id,
                    query="Inspect this",
                    runner_factory=lambda context: EmptyFinalReplyRunner(),
                )

        self.assertEqual(
            load_conversation_messages(conversation_id=conversation.id),
            [{"role": "user", "content": "Inspect this"}],
        )
