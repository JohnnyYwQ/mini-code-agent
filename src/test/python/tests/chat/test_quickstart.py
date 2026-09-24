"""Exercise first-use entry points with the real SDK and no external services."""

import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
from anthropic import Anthropic
from chat.application import load_conversation_messages
from chat.composition import close_production_memory
from django.test import Client, TestCase


class QuickStartTests(TestCase):
    def setUp(self):
        self.workspace = TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.path = Path(self.workspace.name)
        self.env = patch.dict(
            os.environ,
            {
                "MODEL_ID": "test-model",
                "ANTHROPIC_API_KEY": "test-key",
                "ANTHROPIC_BASE_URL": "https://model.invalid",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        close_production_memory()
        self.addCleanup(close_production_memory)
        self.client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.csrf = self.client.cookies["csrftoken"].value
        with patch("chat.views.DEFAULT_WEB_WORKSPACE", self.path):
            response = self.client.post(
                "/conversations/new/", HTTP_X_CSRFTOKEN=self.csrf
            )
        self.assertEqual(response.status_code, 302)
        self.conversation_id = response.url.split("conversation=", 1)[1]

    def post_message(self, transport, *, memory_enabled=True):
        with (
            patch.dict(
                os.environ, {"MEMORY_ENABLED": "true" if memory_enabled else "false"}
            ),
            Anthropic(
                api_key="test-key",
                max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(transport)),
            ) as sdk,
            patch("chat.composition.Anthropic", return_value=sdk),
            patch(
                "core.memory.composition.build_multilingual_e5_base_encoder",
                side_effect=ValueError("Model cache unavailable"),
            ) as load_models,
            patch("chat.composition.logger.warning") as warning,
        ):
            response = self.client.post(
                "/api/chat/",
                data={"conversation_id": self.conversation_id, "message": "hello"},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=self.csrf,
            )
        if memory_enabled:
            load_models.assert_called_once()
            self.assertIn("continuing without Memory", warning.call_args.args[0])
        else:
            load_models.assert_not_called()
            warning.assert_not_called()
        return response

    def test_first_message_can_skip_memory_model_downloads(self):
        def respond(request):
            body = json.loads(request.content)
            self.assertFalse(any(tool["name"] == "remember" for tool in body["tools"]))
            return httpx.Response(
                200,
                json={
                    "id": "msg-test",
                    "type": "message",
                    "role": "assistant",
                    "model": "test-model",
                    "content": [{"type": "text", "text": "hello without downloads"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 10, "output_tokens": 10},
                },
            )

        response = self.post_message(respond, memory_enabled=False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["assistant"], "hello without downloads")

    def test_web_tool_turn_without_memory_then_cli_list_and_resume(self):
        import cli

        (self.path / "greeting.txt").write_text("hello from workspace")
        requests = []

        def respond(request):
            body = json.loads(request.content)
            requests.append(body)
            self.assertEqual(body["model"], "test-model")
            self.assertTrue(any(tool["name"] == "read_file" for tool in body["tools"]))
            first = len(requests) == 1
            if not first:
                result = body["messages"][-1]["content"][0]
                self.assertEqual(result["tool_use_id"], "read-1")
                self.assertEqual(result["content"], "hello from workspace")
            return httpx.Response(
                200,
                json={
                    "id": "msg-test",
                    "type": "message",
                    "role": "assistant",
                    "model": "test-model",
                    "content": (
                        [
                            {
                                "type": "tool_use",
                                "id": "read-1",
                                "name": "read_file",
                                "input": {"path": "greeting.txt"},
                            }
                        ]
                        if first
                        else [{"type": "text", "text": "hello from workspace"}]
                    ),
                    "stop_reason": "tool_use" if first else "end_turn",
                    "usage": {"input_tokens": 10, "output_tokens": 10},
                },
            )

        response = self.post_message(respond)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["assistant"], "hello from workspace")
        self.assertEqual(len(requests), 2)
        self.assertEqual(
            [
                message["role"]
                for message in load_conversation_messages(
                    conversation_id=self.conversation_id
                )
            ],
            ["user", "assistant", "user", "assistant"],
        )
        page = self.client.get("/", {"conversation": self.conversation_id})
        self.assertContains(page, "hello from workspace")

        for args in (["--list"], ["--resume", self.conversation_id]):
            with (
                self.subTest(args=args),
                patch("sys.argv", ["cli.py", *args]),
                patch("cli.Path.cwd", return_value=self.path),
                patch.object(cli.session, "prompt", side_effect=EOFError),
                redirect_stdout(io.StringIO()) as output,
            ):
                cli.main()
                self.assertIn(self.conversation_id, output.getvalue())
                if "--resume" in args:
                    self.assertIn("hello from workspace", output.getvalue())

    def test_http_failures_explain_configuration_or_service_problem(self):
        for status, hint in (
            (400, "request"),
            (401, "ANTHROPIC_API_KEY"),
            (403, "access"),
            (404, "MODEL_ID"),
            (429, "rate limit"),
            (500, "service"),
        ):
            with self.subTest(status=status):

                def respond(request):
                    return httpx.Response(
                        status,
                        json={"error": {"message": "private upstream response"}},
                    )

                response = self.post_message(respond)
                self.assertEqual(response.status_code, 500)
                error = response.json()["error"]
                self.assertIn(str(status), error)
                self.assertIn(hint, error)
                self.assertNotIn("private upstream response", error)

    def test_connection_and_timeout_failures_are_distinguishable(self):
        for failure, hint in (
            (httpx.ConnectError, "ANTHROPIC_BASE_URL"),
            (httpx.ReadTimeout, "timed out"),
        ):
            with self.subTest(failure=failure):

                def respond(request):
                    raise failure("private transport details", request=request)

                response = self.post_message(respond)
                self.assertEqual(response.status_code, 500)
                error = response.json()["error"]
                self.assertIn(hint, error)
                self.assertNotIn("private transport details", error)
