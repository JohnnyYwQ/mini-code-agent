# Mini Code Agent

[中文](README.md) · [Usage guide](docs/usage.en.md) · [Evaluation details](docs/memory-and-evaluation.en.md)

[![CI](https://github.com/JohnnyYwQ/mini-code-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/JohnnyYwQ/mini-code-agent/actions/workflows/ci.yml)
![Python 3.13+](https://img.shields.io/badge/Python-3.13%2B-3776AB)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**A local coding assistant for your browser or terminal.**

Ask the Agent to read and edit code, run commands, and continue earlier Conversations. Optional cross-conversation Memory can remember your preferences and project conventions.

> Intended for personal use in trusted local projects. The Agent can modify files and run commands. Do not expose the service to the public internet.

## Quick start

You need Python 3.13+, [uv](https://docs.astral.sh/uv/getting-started/installation/), and a model ID and API key for Anthropic or a compatible service.

### 1. Install

```bash
git clone https://github.com/JohnnyYwQ/mini-code-agent.git
cd mini-code-agent
uv sync --locked
cp .env.example .env
```

### 2. Configure

Edit `.env` and replace the placeholders with your model ID and API key. For a compatible service, uncomment `ANTHROPIC_BASE_URL` and enter its base URL.

```env
MODEL_ID=your_model_id
ANTHROPIC_API_KEY=your_api_key
MEMORY_ENABLED=false
# ANTHROPIC_BASE_URL=
```

Keep `MEMORY_ENABLED=false` to start chatting without downloading Memory models. Conversation history is still saved. Do not commit `.env` with your API key.

### 3. Start

Before using either the browser or CLI for the first time, initialize the database:

```bash
uv run --locked python src/main/python/manage.py migrate
```

Start the Web app:

```bash
uv run --locked python src/main/python/manage.py runserver
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/), click **New conversation**, enter a message, and click **Send**. Try: “Look through this project and explain what it does and how to run it.”

Click an existing Conversation in the sidebar to continue it.

## Use the terminal

After installation, configuration, and database initialization, you can also start the CLI directly:

```bash
uv run --locked python src/main/python/cli.py
```

List Conversations in the current project, then resume one using its UUID:

```bash
uv run --locked python src/main/python/cli.py --list
uv run --locked python src/main/python/cli.py --resume <conversation-uuid>
```

Replace `<conversation-uuid>` with a UUID from the list. Type `exit` or press `Ctrl-C` to quit.

To work on another project, start the CLI from that project's directory:

```bash
cd /path/to/workspace
uv run --project /path/to/mini-code-agent \
  python /path/to/mini-code-agent/src/main/python/cli.py
```

Replace the example paths with your actual paths. The Agent will work with files and run commands in the current project.

## Enable cross-conversation Memory (optional)

Set `MEMORY_ENABLED=true` in `.env`, then restart Web or CLI.

First use requires additional model downloads. Allow network access for the downloads and reserve several GB of disk space; the first reply may take longer. Keep it `false` if you only need the coding assistant. If you already have a `.env` file, add this setting manually.

See the [usage guide](docs/usage.en.md) for more configuration options, troubleshooting, and development commands.

## Evaluation results

LongMemEval-S Memory retrieval evaluation, with **419 scored cases**:

| Retrieval pipeline | RecallAll@5 | NDCG@5 | RecallAll@10 | NDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| E5 + BM25 + RRF + BGE | **92.60%** | **94.74%** | **97.61%** | **95.69%** |

These figures come from existing run record `20260816-cu124-v1`; the complete artifacts have not been published in the repository and independently reverified. They measure Memory retrieval, not answer accuracy or an official leaderboard score. [Evaluation protocol, full comparison, and reproduction →](docs/memory-and-evaluation.en.md)

## Further reading

- [Usage and contribution guide](docs/usage.en.md)
- [Memory and evaluation details](docs/memory-and-evaluation.en.md)
- [Architecture guide](docs/architecture.en.md)

## Acknowledgements and license

The early Agent Loop was inspired by [shareAI-lab/learn-claude-code](https://github.com/shareAI-lab/learn-claude-code).

[MIT License](LICENSE) © 2026 JohnnyYwQ
