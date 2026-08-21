# 使用与贡献指南

[English](usage.en.md) · [返回中文首页](../README.md) · [架构指南](architecture.md) · [Memory 与评测指南](memory-and-evaluation.md)

本指南面向首次运行当前 Web 或 CLI 的读者，以及希望复现项目开发检查的贡献者。它解释可信本地边界、配置、入口、JSON API、Memory 存储和质量检查；LongMemEval Retrieval Baseline 的独立 CUDA 流程见 [Memory 与评测指南](memory-and-evaluation.md)。

> **先阅读安全边界：** 这是可信本地、单 User 的开发工具，不具备生产认证或多用户隔离。不要把 Web 应用或 `/api/chat/` 直接暴露到公网；Agent 可以在选定工作区运行 shell 命令并修改文件。

## 运行应用

### 依赖与安装

项目要求 Python 3.13+ 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。在仓库根目录同步锁定依赖：

```bash
uv sync --locked
```

该命令在根目录创建或更新 `.venv`。普通 Web、CLI 和开发工作流使用默认的 CPU 与开发依赖，后续命令无需手动激活环境，直接通过 `uv run` 执行即可。

`cuda-eval` 是用于固定 Linux CUDA 主机的单独可选依赖，且与普通 CPU 依赖选择冲突。不要在日常开发环境中添加它；需要复现 LongMemEval Retrieval Baseline 时，请遵循 [Memory 与评测指南](memory-and-evaluation.md) 的固定主机流程。

### 配置环境

从示例创建本地配置文件：

```bash
cp .env.example .env
```

编辑 `.env`，填写真实模型与凭据。不要提交 `.env`，也不要把凭据写入截图、issue 或日志：

```env
MODEL_ID=your_model_id
ANTHROPIC_API_KEY=your_api_key
# ANTHROPIC_BASE_URL=
# MEMORY_QDRANT_LOCATION=~/.mini-code-agent/qdrant
# MEMORY_QDRANT_COLLECTION=mini_code_agent_memories
# MEMORY_MAX_TOKENS=1200
```

| 变量 | 用途与默认值 |
| --- | --- |
| `MODEL_ID` | 必填；传给 Anthropic Messages API 的模型 ID。 |
| `ANTHROPIC_API_KEY` | 正常 Anthropic API 调用所需的凭据。 |
| `ANTHROPIC_BASE_URL` | 可选的 Anthropic-compatible API 基础地址。 |
| `MEMORY_QDRANT_LOCATION` | 可选的本地路径或完整 `http(s)://` Qdrant 服务 URL；默认 `~/.mini-code-agent/qdrant`。 |
| `MEMORY_QDRANT_COLLECTION` | 可选 collection 名；默认 `mini_code_agent_memories`。 |
| `MEMORY_MAX_TOKENS` | 可选的 Memory 提取输出上限；默认 `1200`。 |

### 数据库与 Web

先创建 SQLite 数据库表，再启动 Django 开发服务器：

```bash
uv run --locked python config/manage.py migrate
uv run --locked python config/manage.py runserver
```

在浏览器中打开 `http://127.0.0.1:8000/`，点击 **New conversation** 后即可发送消息。Web 入口为当前进程的工作目录创建 Conversation；侧栏按 Memory Space（工作区）分组展示本地 User 的 Conversation。选择一个已有 Conversation 后，新的 Turn 会继续在该 Conversation 的工作区运行。

### CLI

CLI 从当前目录解析工作区。没有参数时会创建一个新的 Conversation 并打印其 UUID：

```bash
uv run --locked python config/cli.py
```

仅能列出或恢复当前 Memory Space 的 Conversation：

```bash
uv run --locked python config/cli.py --list
uv run --locked python config/cli.py --resume <conversation-uuid>
```

输入 `q`、`exit`、空行、`Ctrl-C` 或 EOF 退出。移动或重命名工作区会产生新的 Memory Space，不能通过 CLI 从新路径恢复旧路径的 Conversation。

要在另一个工作区运行 Agent、同时继续使用本项目的环境，请从目标目录执行：

```bash
cd /path/to/workspace
uv run --project /path/to/mini-code-agent \
  python /path/to/mini-code-agent/config/cli.py
```

这会把 Conversation、Memory Space、文件工具和 shell 绑定到 `/path/to/workspace`，而依赖仍来自 `mini-code-agent`。若 Web 中保存的工作区已不存在，其 Transcript 仍可阅读，但无法发起新的 Turn 或执行工具。

## Web 与 JSON API

### Web 使用

Web 是推荐入口：它负责创建和选择 Conversation，并自动从页面的 CSRF token 发起 JSON 请求。Conversation Transcript 是持久化对话历史；每个 Turn 的 recalled Memory 只是临时 system context，二者并不相同。有关 Agent Runtime、Memory Context 和工具边界的说明见[架构指南](architecture.md)。

Web 会对潜在破坏性的 `bash` 命令拒绝确认；这不是安全沙箱。需要交互式确认时，使用受信任终端中的 CLI，并先审查命令。

### CSRF 保护的 JSON API

`POST /api/chat/` 接收 JSON 对象：`conversation_id` 为已有 Conversation UUID，`message` 为非空字符串。成功时返回 `ok`、`conversation_id`、`title`、规范化后的 `user`、可见 `assistant` 文本和当前固定为空的 `tool_trace`。缺失或无效输入返回 400；未知 Conversation 返回 404；工作区不可用返回 409；模型或运行时失败返回 5xx。

API 受 Django CSRF middleware 保护。先在 Web 中创建 Conversation，并从其 URL 的 `conversation` 参数或 CLI 输出取得 UUID。然后请求首页以保存 CSRF cookie：

```bash
curl -c cookies.txt http://127.0.0.1:8000/
```

从 `cookies.txt` 复制真实 `csrftoken` 值，再将匹配 cookie 和请求头一起发送：

```bash
curl -X POST http://127.0.0.1:8000/api/chat/ \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: <csrftoken-from-cookies.txt>" \
  -d '{"conversation_id":"<conversation-uuid>","message":"hello"}'
```

不要为了脚本调用关闭 CSRF，也不要把本地 cookie 或凭据提交到仓库。浏览器界面已经处理这一路径。

## Memory 与 Qdrant

### 按需下载 BGE

Memory 使用 E5 dense、BM25 keyword 和 BGE Reranking。`BAAI/bge-reranker-v2-m3` 由 `BGEReranker` 延迟加载：第一次发生 Memory recall 或运行 BGE 评测时会下载模型。请在首次 Memory-enabled run 前预留数 GB 磁盘空间；之后会复用本地缓存。

Memory 初始化或检索失败时，当前 Agent Runtime 会记录错误并继续运行，但不带 recalled Memory。这不表示模型配置或持久存储已经正确；应先检查环境变量、网络访问、模型缓存和 Qdrant 位置。

### 本地与服务型 Qdrant

默认 `MEMORY_QDRANT_LOCATION` 是本地 `~/.mini-code-agent/qdrant`，适合一个进程使用。Web 和 CLI 同时访问时，请使用带 scheme 的共享 Qdrant service URL，例如：

```env
MEMORY_QDRANT_LOCATION=http://127.0.0.1:6333
```

本机 Qdrant service 经过系统代理时，设置 loopback bypass，避免请求被错误转发：

```bash
export NO_PROXY=localhost,127.0.0.1
```

Qdrant 保留 Memory 的当前 Source Text；它不替代 Django 中持久化的 Conversation Transcript。Scope、User Memory 和 Space Memory 的行为见 [Memory 与评测指南](memory-and-evaluation.md)。

## 安全与限制

### 可信本地边界

版本 0.2 自动创建一个没有可用密码的本地 User，Web 与 CLI 共用它以保持 Conversation、Memory Space 和 User Memory 的所有权稳定。它没有登录、API token、客户端提供的 `user_id`、多 User 隔离或远程部署认证。

Django 当前使用开发设置，包括 `DEBUG = True` 和空 `ALLOWED_HOSTS`。这适用于本机开发，不是生产部署配置。不要将当前 Web 服务、JSON API 或 SQLite/Qdrant 数据直接发布到公网。

### 工具与工作区风险

Agent Runtime 将 `bash`、`read_file`、`write_file`、`edit_file` 等工具固定在所选 Conversation 的工作区。文件工具会拒绝解析后逃离工作区的路径，但 `write_file` 和 `edit_file` 仍会修改该工作区中的文件。

`bash` 使用 `subprocess.run(..., shell=True)`。当前 denylist 只拒绝少数明确模式；潜在破坏性命令依赖入口的确认策略，因此不构成完整沙箱。只在你信任的本地工作区使用该工具，并审查它可能读写或执行的内容。

## 贡献与检查

### 日常质量检查

安装后，以下命令使用锁文件中定义的开发工具：

```bash
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy
uv run --locked python config/manage.py test chat tests.memory
```

安装 Git hook 并手动运行全部 hook：

```bash
uv run --locked pre-commit install
uv run --locked pre-commit run --all-files
```

pre-commit 在提交时运行 Ruff（可能自动修复或格式化）和 mypy。如果 hook 修改文件，提交会停止；检查改动、重新暂存后再次提交。

### 覆盖率与 CI

生成终端覆盖率报告：

```bash
uv run --locked coverage erase
uv run --locked coverage run config/manage.py test chat tests.memory
uv run --locked coverage report -m
```

生成 HTML 覆盖率报告：

```bash
uv run --locked coverage html
```

报告写入 `htmlcov/index.html`。GitHub Actions 在 push、pull request 和手动触发时，以 `uv sync --locked --dev` 同步依赖，并在 Python 3.13 上运行 Ruff format/check、mypy、带 coverage 的测试和 coverage 报告。

## 故障排查与当前限制

### 启动前检查

若 CLI 或 Web 无法调用模型，先确认 `.env` 中的 `MODEL_ID` 与 `ANTHROPIC_API_KEY`，再检查可选 `ANTHROPIC_BASE_URL` 是否为目标服务的完整地址。使用 `--help` 检查 CLI 入口，而不是复用旧路径：

```bash
uv run --locked python config/cli.py --help
```

若 Memory 不可用，先检查 BGE 下载所需的磁盘空间、Qdrant 路径或服务 URL、代理 bypass 和模型/API 凭据。Memory 失败的降级只保证 Agent Runtime 可以继续，不保证 Memory 已配置完成。

### 当前产品限制

- 模型回复不流式输出。
- 当前没有完整工具调用轨迹可视化。
- Memory UPDATE、DELETE、Memory Event 集成和自动索引恢复尚未完成。
- 工作区路径变更不会自动迁移或重新绑定旧 Memory Space。
- 远程、多用户或生产使用需要真实认证、隔离和更强的工具沙箱；当前版本不提供这些能力。
