import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase

from chat.application import (
    append_conversation_message,
    load_conversation_messages,
    start_conversation,
)


class ChatApiJsonFallbackTests(TestCase):
    def setUp(self):
        self.workspace = TemporaryDirectory()
        self.conversation = start_conversation(workspace_path=Path(self.workspace.name))

    def tearDown(self):
        self.workspace.cleanup()

    def post_json(self, payload):
        payload.setdefault("conversation_id", str(self.conversation.id))
        return self.client.post(
            "/api/chat/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_get_chat_api_returns_json_405(self):
        response = self.client.get("/api/chat/")

        self.assertEqual(response.status_code, 405)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "Method not allowed")

    def test_invalid_json_returns_json_400(self):
        response = self.client.post(
            "/api/chat/",
            data="not-json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "Invalid JSON")

    def test_empty_message_returns_json_400(self):
        response = self.post_json({"message": "   "})

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "Message is required")

    def test_agent_loop_exception_returns_json_500(self):
        with patch(
            "chat.views.build_web_runner",
            side_effect=RuntimeError("boom"),
        ):
            response = self.post_json({"message": "hello"})

        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "Agent failed: boom")
        self.assertEqual(
            load_conversation_messages(conversation_id=self.conversation.id),
            [{"role": "user", "content": "hello"}],
        )

    def test_agent_loop_success_returns_assistant_json_200(self):
        class FakeRunner:
            def run(self, *, messages, latest_user_query):
                return [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "hello from test"}],
                    }
                ]

        with patch("chat.views.build_web_runner", return_value=FakeRunner()):
            response = self.post_json({"message": "hello"})

        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["user"], "hello")
        self.assertEqual(data["assistant"], "hello from test")
        self.assertEqual(data["tool_trace"], [])
        self.assertEqual(data["conversation_id"], str(self.conversation.id))

    def test_missing_conversation_id_returns_json_400(self):
        response = self.client.post(
            "/api/chat/",
            data=json.dumps({"message": "hello"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Conversation is required")

    def test_missing_workspace_returns_json_409_without_appending_message(self):
        self.workspace.cleanup()

        response = self.post_json({"message": "hello"})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            load_conversation_messages(conversation_id=self.conversation.id),
            [],
        )


class ConversationPageTests(TestCase):
    def test_sidebar_groups_all_workspaces_and_restores_selected_transcript(self):
        with (
            TemporaryDirectory() as first_workspace,
            TemporaryDirectory() as second_workspace,
        ):
            selected = start_conversation(workspace_path=Path(first_workspace))
            other = start_conversation(workspace_path=Path(second_workspace))
            append_conversation_message(
                conversation_id=selected.id,
                message={"role": "user", "content": "Selected question"},
            )
            append_conversation_message(
                conversation_id=selected.id,
                message={
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Selected answer"}],
                },
            )
            append_conversation_message(
                conversation_id=other.id,
                message={"role": "user", "content": "Other workspace"},
            )

            response = self.client.get(
                "/",
                {"conversation": str(selected.id)},
            )

        self.assertContains(response, str(Path(first_workspace).resolve()))
        self.assertContains(response, str(Path(second_workspace).resolve()))
        self.assertContains(response, "Selected question")
        self.assertContains(response, "Selected answer")
        self.assertContains(response, "Other workspace")
