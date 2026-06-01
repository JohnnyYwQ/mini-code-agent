# Mini Code Agent

## Project Overview

Mini Code Agent is a small Django-based coding agent project. It provides a web chat page and a JSON chat API that send user messages to an Anthropic Claude Messages API agent loop.

The agent can call local tools, observe tool results, and continue the conversation until Claude returns a final response. It is intended for local development and learning, not for public production deployment.

## Features

- Django web chat page at `/`.
- JSON chat endpoint at `/api/chat/`.
- Anthropic Claude Messages API integration through the `anthropic` Python SDK.
- `tool_use` / `tool_result` agent loop.
- Local agent tools:
  - `bash`: run shell commands in the workspace.
  - `read_file`: read files from the workspace.
  - `write_file`: write files inside the workspace.
  - `edit_file`: replace text in a file inside the workspace.
  - `todo`: maintain an in-memory task list for the agent.
  - `task`: start a subagent with fresh conversation context.
- `safe_path` workspace path restriction for file tools.
- CLI and web entry points.

## Tech Stack

- Python 3
- Django 5.2
- Anthropic Python SDK
- python-dotenv
- HTML, CSS, and vanilla JavaScript for the web chat UI

## Project Structure

```text
.
├── .env.example
├── requirements.txt
└── config
    ├── manage.py
    ├── config
    │   ├── settings.py
    │   ├── urls.py
    │   ├── asgi.py
    │   └── wsgi.py
    ├── chat
    │   ├── urls.py
    │   ├── views.py
    │   ├── templates/chat/index.html
    │   └── static/chat/
    │       ├── chat.js
    │       └── style.css
    └── core
        └── agent.py
```

Key files:

- `config/core/agent.py`: Anthropic client setup, agent loop, tool definitions, tool handlers, CLI entry point, and workspace path checks.
- `config/chat/views.py`: Django web page view and `/api/chat/` JSON API.
- `config/chat/static/chat/chat.js`: browser-side form handling and JSON request to `/api/chat/`.
- `config/chat/templates/chat/index.html`: web chat page template.

## How It Works

1. A user sends a message from the web page or CLI.
2. The message is appended to an in-memory conversation history.
3. `agent_loop()` calls the Anthropic Claude Messages API with the current messages and available tools.
4. If Claude returns `tool_use`, the matching local Python handler runs.
5. Tool output is appended back as `tool_result`.
6. The loop continues until Claude returns a non-tool final response.
7. The web API returns the assistant text as JSON, or the CLI prints it to stdout.

The web entry point uses a process-level `AGENT_HISTORY` list in `config/chat/views.py`. The CLI entry point uses a local `history` list inside `config/core/agent.py`.

## Quick Start

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a local `.env` file:

```bash
cp .env.example .env
```

Edit `.env` and set your Anthropic credentials:

```env
MODEL_ID=claude-3-5-sonnet-latest
ANTHROPIC_API_KEY=your_api_key_here
# ANTHROPIC_BASE_URL=
```

Run the Django web app:

```bash
python3 config/manage.py runserver
```

This command keeps running and occupies the current terminal. Keep this terminal open while testing the app.

Open the web UI in a browser:

```text
http://127.0.0.1:8000/
```

The recommended test path is the browser web UI. The frontend page includes Django's CSRF token and sends it automatically when posting to `/api/chat/`.

Call the JSON API with curl:

`/api/chat/` is protected by Django CSRF middleware. A header like `X-CSRFToken: <csrf-token>` is not enough by itself, because Django also expects the matching CSRF cookie.

Run these curl commands in another terminal window or tab while `python3 config/manage.py runserver` is still running.

Step 1: request the homepage and save cookies:

```bash
curl -c cookies.txt http://127.0.0.1:8000/
```

Step 2: open `cookies.txt` and copy the real `csrftoken` value.

Step 3: send the JSON request with both the saved cookie and the matching CSRF token header:

```bash
curl -X POST http://127.0.0.1:8000/api/chat/ \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: <real-csrftoken-from-cookies.txt>" \
  -d '{"message":"hello"}'
```

If you see `403 CSRF cookie not set`, the request reached Django, but the CSRF cookie is missing or the token does not match. It does not mean the URL is unreachable or that the `/api/chat/` route is missing.

Run the CLI entry point:

```bash
python3 config/core/agent.py
```

Exit the CLI with `q`, `exit`, an empty input, `Ctrl-C`, or EOF.

## Environment Variables

- `MODEL_ID`: required. The Claude model name passed to the Messages API.
- `ANTHROPIC_API_KEY`: required for normal Anthropic API usage.
- `ANTHROPIC_BASE_URL`: optional. Custom Anthropic-compatible base URL. When this is set, the current code removes `ANTHROPIC_AUTH_TOKEN` from the process environment.

Environment variables are loaded with `python-dotenv` from `.env`.

## Safety Notes

- This project is designed for local development.
- The `bash` tool executes shell commands with `subprocess.run(..., shell=True)` in the current workspace. It has a small denylist for some dangerous commands, but it is not a complete sandbox.
- Do not expose the current web app or agent API to the public internet.
- The file tools use `safe_path()` so paths must stay inside the workspace resolved from `Path.cwd()`.
- `write_file` and `edit_file` can modify files inside the workspace.
- The web conversation history is stored in process memory and is shared by the running Django process.
- Django currently runs with development settings such as `DEBUG = True` and empty `ALLOWED_HOSTS`.

## Current Limitations

- No database-backed chat or tool history storage. Django has a default SQLite configuration, but the chat history is not persisted in database models.
- No RAG implementation.
- No embedding pipeline.
- No vector database integration.
- No Docker setup.
- No streaming output from the model or web API.
- No user account system or per-user conversation isolation.
- No implemented tool trace visualization in the active API flow.
- No complete automated test suite.
- The `bash` tool is suitable only for trusted local development environments.

## Roadmap

- Add database-backed conversation and tool-call persistence.
- Add RAG support.
- Add embedding generation and indexing.
- Add vector database integration.
- Add Docker support for local deployment.
- Add streaming responses for the web UI and JSON API.
- Add user accounts and per-user session isolation.
- Add tool trace visualization for tool calls and results.
- Expand automated test coverage.
