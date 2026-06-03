import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from .views import AGENT_HISTORY
from core.agent import agent_loop

os.environ.setdefault("MODEL_ID", "test-model")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-api-key")

class ChatApiJsonFallbackTests(TestCase):
    def setUp(self):
        AGENT_HISTORY.clear()

    def tearDown(self):
        AGENT_HISTORY.clear()

    def post_json(self, payload):
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

    def  test_empty_message_returns_json_400(self):
        response = self.post_json({"message": "   "})

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "Message is required")

    def test_agent_loop_exception_returns_json_500(self):
        with patch("chat.views.agent_loop", side_effect=RuntimeError("boom")):
            response = self.post_json({"message": "hello"})
        
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "Agent failed: boom")

    def test_agent_loop_success_returns_assistant_json_200(self):
        def fake_agent_loop(history):
            history.append({
                "role": "assistant",
                "content": [SimpleNamespace(text="hello from test")]
            })
    
        with patch("chat.views.agent_loop", side_effect=fake_agent_loop):
            response = self.post_json({"message": "hello"})

        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["user"], "hello")
        self.assertEqual(data["assistant"], "hello from test")
        self.assertEqual(data["tool_trace"], [])    

class AgentLoopTests(TestCase):
    @patch("core.agent.MAX_ROUND", 3)
    @patch("core.agent.client.messages.create")
    def test_agent_loop_raises_when_max_round_exceeded(self, mock_create):
        fake_tool_block = SimpleNamespace(
            type="tool_use",
            name="unknown tool",
            input={},
            id="toolu_test",
        )

        fake_response = SimpleNamespace(
            stop_reason="tool_use",
            content=[fake_tool_block]
        )

        mock_create.return_value = fake_response

        messages = [{"role": "user", "content": "keep using tools"}]

        with self.assertRaises(RuntimeError) as ctx:
            agent_loop(messages)

        self.assertIn("Agent exceeded max rounds", str(ctx.exception))
        self.assertEqual(mock_create.call_count, 3)        