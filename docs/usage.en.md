# Usage and Contributor Guide

[中文](usage.md) · [Back to English README](../README.en.md) · [Architecture guide](architecture.en.md) · [Memory and evaluation guide](memory-and-evaluation.en.md)

This guide is for first-time users of the current Web or CLI experience and contributors who want to reproduce the repository's development checks. It covers the trusted-local boundary, configuration, entry points, JSON API, Memory storage, and quality checks. See the [Memory and evaluation guide](memory-and-evaluation.en.md) for the separate CUDA workflow behind the LongMemEval Retrieval Baseline.

> **Read the security boundary first:** this is a trusted-local, single-User development tool. It has no production authentication or multi-User isolation. Django uses development settings including `DEBUG = True`; embedded local Qdrant suits one process, and concurrent Web/CLI access needs a shared service URL. Do not expose the Web app or `/api/chat/` to the public internet; the Agent can run shell commands and change files in the selected workspace.

## Run the application

### Requirements and installation

The project requires Python 3.13+ and [uv](https://docs.astral.sh/uv/getting-started/installation/). Sync the locked dependencies from the repository root:

```bash
uv sync --locked
```

This creates or updates `.venv` in the project root. Ordinary Web, CLI, and development workflows use the default CPU and development dependencies. The remaining commands use `uv run`, so manual environment activation is not normally needed.

`cuda-eval` is a separate optional dependency selection for the pinned Linux CUDA host and conflicts with the ordinary CPU selection. Do not add it to an everyday development environment. To reproduce the LongMemEval Retrieval Baseline, follow the pinned-host workflow in the [Memory and evaluation guide](memory-and-evaluation.en.md).

### Configure the environment

Create a local configuration file from the example:

```bash
cp .env.example .env
```

Edit `.env` with a real model and credentials. Never commit `.env`, or put credentials in screenshots, issues, or logs:

```env
MODEL_ID=your_model_id
ANTHROPIC_API_KEY=your_api_key
# ANTHROPIC_BASE_URL=
# MEMORY_QDRANT_LOCATION=~/.mini-code-agent/qdrant
# MEMORY_QDRANT_COLLECTION=mini_code_agent_memories
# MEMORY_MAX_TOKENS=1200
```

| Variable | Purpose and default |
| --- | --- |
| `MODEL_ID` | Required; the model ID passed to the Anthropic Messages API. |
| `ANTHROPIC_API_KEY` | Credential required for ordinary Anthropic API calls. |
| `ANTHROPIC_BASE_URL` | Optional Anthropic-compatible API base URL. |
| `MEMORY_QDRANT_LOCATION` | Optional local path or complete `http(s)://` Qdrant service URL; defaults to `~/.mini-code-agent/qdrant`. |
| `MEMORY_QDRANT_COLLECTION` | Optional collection name; defaults to `mini_code_agent_memories`. |
| `MEMORY_MAX_TOKENS` | Optional Memory-extraction output limit; defaults to `1200`. |

### Database and Web

Create the SQLite database tables, then start Django's development server:

```bash
uv run --locked python config/manage.py migrate
uv run --locked python config/manage.py runserver
```

Open `http://127.0.0.1:8000/` in a browser, select **New conversation**, then send a message. With no Conversation selected, the Web entry point creates one for the process's current workspace. With a Conversation selected, the new Conversation inherits that Conversation's workspace. Its sidebar shows the local User's Conversations grouped by Memory Space (workspace). New Turns run in the selected Conversation's workspace.

### CLI

The CLI resolves its workspace from the current directory. Without arguments it creates a new Conversation and prints its UUID:

```bash
uv run --locked python config/cli.py
```

It can list or resume only Conversations in the current Memory Space:

```bash
uv run --locked python config/cli.py --list
uv run --locked python config/cli.py --resume <conversation-uuid>
```

Exit with `q`, `exit`, an empty line, `Ctrl-C`, or EOF. Moving or renaming a workspace creates a new Memory Space, so the CLI cannot resume a Conversation from the old path at the new path.

To run the Agent against another workspace while retaining this project's environment, start from the target directory:

```bash
cd /path/to/workspace
uv run --project /path/to/mini-code-agent \
  python /path/to/mini-code-agent/config/cli.py
```

This binds the Conversation, Memory Space, file tools, and shell to `/path/to/workspace`, while dependencies still come from `mini-code-agent`. If a Web-stored workspace no longer exists, its Conversation Transcript remains readable but new Turns and tool execution are unavailable.

## Web and JSON API

### Use the Web interface

The Web interface is the recommended entry point. It creates and selects Conversations, then issues JSON requests with the page's CSRF token. A Conversation Transcript is durable conversation history; recalled Memory is temporary system context for a Turn, not the same thing. See the [architecture guide](architecture.en.md) for Agent Runtime, Memory Context, and tool boundaries.

The Web entry point declines confirmation for potentially destructive `bash` commands. That is not a security sandbox. Use the CLI in a trusted terminal when interactive confirmation is appropriate, and review the command first.

### CSRF-protected JSON API

`POST /api/chat/` accepts a JSON object whose `conversation_id` is an existing Conversation UUID and whose `message` is a non-empty string. A successful response has `ok`, `conversation_id`, `title`, normalized `user`, visible `assistant` text, and the currently fixed-empty `tool_trace`. Missing or invalid input returns 400; an unknown Conversation returns 404; an unavailable workspace returns 409; model or runtime failures return 5xx.

The API is protected by Django's CSRF middleware. First create a Conversation in the Web interface, then get its UUID from the `conversation` URL parameter or CLI output. Request the homepage to save a CSRF cookie:

```bash
curl -c cookies.txt http://127.0.0.1:8000/
```

Copy the real `csrftoken` from `cookies.txt`, then send both its matching cookie and request header:

```bash
curl -X POST http://127.0.0.1:8000/api/chat/ \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: <csrftoken-from-cookies.txt>" \
  -d '{"conversation_id":"<conversation-uuid>","message":"hello"}'
```

Do not disable CSRF for scripting and do not commit local cookies or credentials. The browser interface already handles this flow.

## Memory and Qdrant

### On-demand BGE download

Memory combines E5 dense, BM25 keyword, and BGE Reranking. `BAAI/bge-reranker-v2-m3` is lazily loaded by `BGEReranker`: its model downloads on the first Memory recall that has candidates to rerank, or during BGE evaluation. Reserve several GB of disk before the first Memory-enabled run; later runs reuse the local cache.

If Memory initialization or retrieval fails, the current Agent Runtime logs the error and continues without recalled Memory. That does not show that model configuration or persistent storage is correct. Check environment variables, network access, model cache, and Qdrant location first.

### Local and service-backed Qdrant

The default `MEMORY_QDRANT_LOCATION` is local `~/.mini-code-agent/qdrant`, which suits one process. When Web and CLI need concurrent access, use a shared Qdrant service URL that includes a scheme, for example:

```env
MEMORY_QDRANT_LOCATION=http://127.0.0.1:6333
```

If a local Qdrant service is subject to a system proxy, bypass it for loopback traffic:

```bash
export NO_PROXY=localhost,127.0.0.1
```

Qdrant retains a Memory's current Source Text; it does not replace Django's durable Conversation Transcript. See the [Memory and evaluation guide](memory-and-evaluation.en.md) for Scope, User Memory, and Space Memory behavior.

## Safety and limitations

### Trusted-local boundary

Version 0.2 automatically creates one local User with an unusable password. Web and CLI share it so ownership of Conversations, Memory Spaces, and User Memory remains stable. The version has no login, API tokens, client-supplied `user_id`, multi-User isolation, or remote-deployment authentication.

Django currently uses development settings, including `DEBUG = True` and an empty `ALLOWED_HOSTS`. That is appropriate for local development, not production deployment. Do not publish the current Web service, JSON API, or SQLite/Qdrant data to the public internet.

### Tool and workspace risks

The Agent Runtime binds `bash`, `read_file`, `write_file`, and `edit_file` to the selected Conversation's workspace. File tools reject paths that resolve outside the workspace, but `write_file` and `edit_file` can still change files inside it.

`bash` uses `subprocess.run(..., shell=True)`. Its current denylist blocks only a few explicit patterns, and potentially destructive commands rely on each entry point's confirmation policy. It is not a complete sandbox. Use it only in local workspaces you trust, and review what it may read, write, or execute.

## Contribute and verify

### Everyday quality checks

After installation, these commands use the development tools defined by the lockfile:

```bash
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy
uv run --locked python config/manage.py test chat tests.memory
```

Install the Git hook and run all hooks manually:

```bash
uv run --locked pre-commit install
uv run --locked pre-commit run --all-files
```

pre-commit runs Ruff (which can fix or format files) and mypy when committing. If a hook changes files, the commit stops; inspect the changes, stage them again, and commit again.

### Coverage and CI

Generate a terminal coverage report:

```bash
uv run --locked coverage erase
uv run --locked coverage run config/manage.py test chat tests.memory
uv run --locked coverage report -m
```

Generate an HTML coverage report:

```bash
uv run --locked coverage html
```

The report is written to `htmlcov/index.html`. GitHub Actions uses `uv sync --locked --dev` for dependency sync, then runs Ruff format/check, mypy, coverage-backed tests, and the coverage report with Python 3.13 on pushes, pull requests, and manual dispatches.

## Troubleshooting and current limits

### Check before startup

If the CLI or Web app cannot call the model, first check `MODEL_ID` and `ANTHROPIC_API_KEY` in `.env`, then confirm that optional `ANTHROPIC_BASE_URL` is a complete address for the intended service. Use `--help` to check the current CLI entry point instead of reusing an old path:

```bash
uv run --locked python config/cli.py --help
```

If Memory is unavailable, check disk space for BGE, the Qdrant path or service URL, proxy bypass, and model/API credentials. Memory's fallback only means the Agent Runtime may continue; it does not mean Memory is configured correctly.

### Current product limits

- Model responses are not streamed.
- There is no complete tool-call trace visualization.
- Memory UPDATE, DELETE, Memory Event integration, and automatic index recovery are incomplete.
- Workspace-path changes do not automatically migrate or rebind the prior Memory Space.
- Remote, multi-User, or production use needs real authentication, isolation, and a stronger tool sandbox; the current version does not provide them.
