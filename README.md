# Mini Code Agent

[English](README.en.md) · [架构指南](docs/architecture.md) · [Memory 与评测指南](docs/memory-and-evaluation.md)

![Mini Code Agent CLI 演示](docs/assets/demo.gif)

## 项目简介

Mini Code Agent 0.2 是一个用于学习和本地开发的小型 Django 编码智能体项目。它提供可恢复的 Web/CLI Conversation、JSON 聊天接口和按工作区隔离的 Agent Runtime，并通过 Anthropic Python SDK 调用 Claude Messages API。

智能体可以调用本地工具、读取工具结果并继续对话，直到模型返回最终回复。项目目前适合可信的本地开发环境，不适合直接部署到公网生产环境。

## 功能

- Django 网页聊天界面：`/`
- JSON 聊天接口：`/api/chat/`
- Django 持久化 Conversation 与完整顶层消息（含 tool-use/tool-result）
- Web 左侧栏按工作区分组全部 Conversation，并支持跨工作区恢复
- CLI 默认新建 Conversation，并可列出或恢复当前工作区的旧 Conversation
- Web 与 CLI 共享一个不可登录的 Django 本地 User
- User/Space 两级 Memory：每轮自动混合检索并使用 BGE 重排，模型可调用无参数 `remember`
- 基于 Anthropic Messages API 的 `tool_use` / `tool_result` 智能体循环
- 本地工具：
  - `bash`：在工作区运行 shell 命令
  - `read_file`：读取工作区内的文件
  - `write_file`：在工作区内写入文件
  - `edit_file`：替换工作区文件中的指定文本
  - `glob`：按 glob 模式查找文件
  - `todo`：维护内存中的任务列表
  - `load_skill`：按名称加载 skill 内容
  - `compact`：压缩较早的对话历史
- 从 `.skills/` 的一级子目录发现 `SKILL.md`
- 上下文压缩、工具结果裁剪和压缩前会话快照
- 工具调用前后及停止阶段的 hook
- 文件工具的工作区路径限制
- Web 和 CLI 两种入口
- Django 测试套件，以及 Ruff、mypy、coverage 和 pre-commit 开发检查

## 技术栈

- Python 3.13+
- Django 5.2
- Anthropic Python SDK
- Qdrant、FastEmbed 和 FlagEmbedding
- uv
- python-dotenv
- prompt_toolkit
- PyYAML
- HTML、CSS 和原生 JavaScript

## 项目结构

```text
.
├── .env.example
├── .github/
│   └── workflows/
│       └── ci.yml
├── .pre-commit-config.yaml
├── .skills/
│   └── code-review/
│       └── SKILL.md
├── LICENSE
├── pyproject.toml
├── uv.lock
└── config/
    ├── cli.py
    ├── manage.py
    ├── config/
    │   ├── settings.py
    │   ├── urls.py
    │   ├── asgi.py
    │   └── wsgi.py
    ├── chat/
    │   ├── application.py
    │   ├── composition.py
    │   ├── models.py
    │   ├── tests/
    │   ├── templates/chat/index.html
    │   ├── static/chat/
    │   ├── urls.py
    │   └── views.py
    ├── core/
        ├── agent_runtime.py
        ├── compaction.py
        ├── memory/
        ├── frontmatter.py
        ├── skills.py
        ├── tooling.py
        └── todo.py
    └── evals/
        └── memory_retrieval/
```

关键文件：

- `config/cli.py`：CLI 接入、Conversation 选择和终端输入输出
- `config/core/tooling.py`：内置工具定义、实现、权限策略和 hook
- `config/core/agent_runtime.py`：绑定 Conversation 工作区的智能体循环、Memory 召回与 `remember`
- `config/core/memory/`：Memory 提取、混合检索、Qdrant adapter 和 production composition
- `config/evals/memory_retrieval/`：内置检索用例、LongMemEval adapter、数据下载与评测入口
- `config/chat/application.py`：可信 User、Memory Space、Conversation、transcript 与 Turn 编排
- `config/chat/composition.py`：Web/CLI 共用的 Agent Runtime 与 Memory 装配入口
- `config/core/compaction.py`：会话快照、工具结果裁剪和上下文压缩
- `config/core/frontmatter.py`：解析 `SKILL.md` 的 YAML frontmatter
- `config/core/skills.py`：发现、注册和加载 skill
- `config/core/todo.py`：校验和维护 todo 状态
- `config/chat/views.py`：网页视图和 `/api/chat/` JSON 接口
- `config/chat/tests/`：单元测试和行为测试
- `pyproject.toml`：项目依赖和 Ruff、mypy、coverage 配置
- `uv.lock`：由 uv 生成的精确依赖锁文件
- `.github/workflows/ci.yml`：在 push、pull request 或手动触发时运行质量检查

`pyproject.toml` 声明项目依赖，`uv.lock` 锁定完整依赖图中的精确版本；二者是项目唯一的依赖管理入口。

## 工作流程

1. Web 或 CLI 选择/创建 Conversation；应用层从它可信地派生本地 User、Memory Space 与工作区。
2. 用户消息先持久化；若 Agent 失败，它会作为未回答消息保留。
3. 每个 Turn 自动混合检索 User Memory 与当前 Space Memory，默认使用 `BAAI/bge-reranker-v2-m3` 重排并召回最多 5 条，作为临时 system context 注入。
4. Conversation 专属 Agent Runtime 在对应工作区运行文件、shell、skills、todo 与 compaction。
5. 模型可调用无参数 `remember`；handler 从最多 5 个已完成 Turn 加当前 Turn 的可见文本提取 Memory。
6. Agent 成功后，本轮 assistant/tool-result 顶层消息作为一个有序批次持久化；失败时不保存部分生成 transcript。
7. Web 与 CLI 从数据库重新加载 Conversation，因此进程重启后仍可恢复。

## 快速开始

先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后在项目根目录同步锁定的依赖：

```bash
uv sync --locked
```

uv 会在项目根目录创建或更新 `.venv`。通常不需要手动激活虚拟环境，后续命令可以通过 `uv run` 执行。

BGE reranker 按需加载；第一次发生 Memory 召回或运行 BGE 评测时会下载模型。请预留数 GB 磁盘空间，后续运行会复用本地缓存。

创建本地环境变量文件：

```bash
cp .env.example .env
```

编辑 `.env`：

```env
MODEL_ID=your_model_id
ANTHROPIC_API_KEY=your_api_key
# ANTHROPIC_BASE_URL=
# MEMORY_QDRANT_LOCATION=/absolute/path/to/qdrant
```

创建数据库表：

```bash
uv run python config/manage.py migrate
```

启动 Django：

```bash
uv run python config/manage.py runserver
```

在浏览器中打开：

```text
http://127.0.0.1:8000/
```

启动 CLI：

```bash
uv run python config/cli.py
```

CLI 默认创建新 Conversation。列出或恢复当前工作区的 Conversation：

```bash
uv run python config/cli.py --list
uv run python config/cli.py --resume <conversation-uuid>
```

输入 `q`、`exit`、空行、`Ctrl-C` 或 EOF 可以退出 CLI。

要让 Agent 操作另一个目录，同时继续使用本项目的虚拟环境，可以从目标工作区执行：

```bash
cd /path/to/workspace
uv run --project /path/to/mini-code-agent \
  python /path/to/mini-code-agent/config/cli.py
```

Conversation 和 Memory Space 会绑定到执行命令时的当前工作区，而依赖仍从 `mini-code-agent` 项目加载。

## Memory 检索评测

评测使用独立的内存 Qdrant，不会读写实际的持久化 Memory。先运行 10 个内置用例的混合检索基线：

```bash
uv run --locked python config/evals/memory_retrieval/run.py
```

在同一个索引上对比不重排与默认 BGE reranker：

```bash
uv run --locked python config/evals/memory_retrieval/run.py \
  --reranker none \
  --reranker bge
```

FlashRank 是可选依赖，默认模型为 `ms-marco-MultiBERT-L-12`：

```bash
uv run --locked --extra flashrank \
  python config/evals/memory_retrieval/run.py \
  --reranker flashrank
```

下载项目锁定且校验 SHA-256 的 LongMemEval-S 数据集，然后先运行 10 题：

```bash
uv run --locked python \
  config/evals/memory_retrieval/download_longmemeval.py

uv run --locked python config/evals/memory_retrieval/run.py \
  --longmemeval config/evals/memory_retrieval/data/longmemeval_s_cleaned.json \
  --max-cases 10 \
  --reranker none \
  --reranker bge
```

删除 `--max-cases 10` 即运行全部可评分用例。下载的数据约 265 MiB，保存在被 Git 忽略的 `config/evals/memory_retrieval/data/` 中。交互式终端会显示建库和逐题评测进度；CI 或重定向输出不会显示进度条。

内置报告包含 Hit@1、Recall@5、MRR@5 和 ScopeLeak；LongMemEval 还会输出 session-level 检索指标。

固定的 Ubuntu 20.04 / RTX 2070 SUPER 主机使用独立的 CUDA 基线入口。它会先运行覆盖六种计分题型、assistant-only 排除项和 abstention 排除项的确定性 smoke，再运行全部可评分题目；E5/BM25/RRF 候选与 BGE 重排分别处于两个进程：

```bash
export MINI_CODE_AGENT_PROXY_URL=http://127.0.0.1:7897  # 按反向隧道的本地端口修改
./scripts/run_longmemeval_cu124.sh
```

脚本复用 `~/.local/share/mini-code-agent/venvs/cu124`，先用锁文件检查环境，仅在不匹配时执行增量 `uv sync`。它也会优先识别已有的 `/tmp/fastembed_cache`、`~/.cache/huggingface/hub` 和仓库内已校验的数据集，不会重复下载完整模型。默认要求工作树干净并至少有 40 GiB 可用空间；需要调试未提交代码时可设置 `MINI_CODE_AGENT_ALLOW_DIRTY=1`，但结果会标为 `provisional`。

最终的 `full/baseline.json` 同时包含 E5、BM25、E5+BM25+RRF 和 E5+BM25+RRF+BGE 的官方 `RecallAll@5`、`NDCG@5`、`RecallAll@10`、`NDCG@10` 公式结果、逐题记录、精确模型 revision 和实际 CUDA provider。E5 的 provider 列表会包含 ONNX Runtime 用于形状与控制节点的隐式 CPU provider；运行前 profile 必须同时证明主计算算子位于 CUDA、CPU 没有主计算算子。BGE 默认重排固定的 RRF top 50 候选，RRF rank constant 为 60；两者都进入缓存身份。该结果称为“official-data/official-metric LongMemEval retrieval baseline”，只评测检索，不是 LongMemEval 端到端 QA 或官方 leaderboard 分数。中断后再次使用同一个 `MINI_CODE_AGENT_RUN_ID` 会从内容寻址的逐题 JSONL 继续。

### 正式 CUDA 基线结果（2026-08-16）

`20260816-cu124-v1` 是一次 `formal` / `full` 运行。官方 cleaned LongMemEval-S 的 500 个源样本中，419 个进入检索评分；30 个 abstention 和 51 个没有 user-side 目标证据的样本按评测协议排除。

| 检索链 | RecallAll@5 | NDCG@5 | RecallAll@10 | NDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 87.35% | 89.33% | 92.12% | 90.44% |
| E5 | 90.93% | 89.92% | 95.94% | 91.20% |
| E5 + BM25 + RRF | 90.69% | 92.17% | 96.42% | 93.26% |
| E5 + BM25 + RRF + BGE | **92.60%** | **94.74%** | **97.61%** | **95.69%** |

BGE 链在四项主指标上都最好；相比 RRF，它将 RecallAll@5、NDCG@5、RecallAll@10 和 NDCG@10 分别提高 1.91、2.57、1.19 和 2.42 个百分点。最终链的 RecallAny@10 为 100%，但 RecallAll@10 仍有 10 题未召回全部目标 session，其中 7 题为 multi-session、3 题为 temporal-reasoning；后续优化应优先改善多 session 覆盖和时间关系检索。

该结果由代码提交 `7b1f9466f3f334bc9f6b58225397c3daee55dbd5` 在 Ubuntu 20.04、RTX 2070 SUPER 8 GiB、NVIDIA 550.142、CUDA 12.4 上产生。E5 的主计算算子经 profile 确认位于 CUDA，BGE 以 FP16 运行于 `cuda:0`。数据集 SHA-256 为 `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`，汇总产物 SHA-256 为 `e267d5696e37a0c006d354c5b21ca5bb8f2620f9a48dbdf5a881f1d6b18b9a34`。

## 调用 JSON API

`/api/chat/` 受 Django CSRF 中间件保护。推荐直接使用网页界面；如需使用 curl，请同时发送匹配的 CSRF cookie 和请求头。

先请求首页并保存 cookie：

```bash
curl -c cookies.txt http://127.0.0.1:8000/
```

从 `cookies.txt` 复制真实的 `csrftoken`，然后发送请求：

```bash
curl -X POST http://127.0.0.1:8000/api/chat/ \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: <csrftoken-from-cookies.txt>" \
  -d '{"conversation_id":"<conversation-uuid>","message":"hello"}'
```

## 开发检查

运行测试：

```bash
uv run python config/manage.py test chat tests.memory
```

运行 Ruff：

```bash
uv run ruff check .
uv run ruff format --check .
```

运行 mypy：

```bash
uv run mypy
```

运行测试并统计覆盖率：

```bash
uv run coverage erase
uv run coverage run config/manage.py test chat tests.memory
uv run coverage report -m
```

生成 HTML 覆盖率报告：

```bash
uv run coverage html
```

报告位于 `htmlcov/index.html`。

全量运行 pre-commit：

```bash
uv run pre-commit run --all-files
```

为当前 clone 安装 Git hook：

```bash
uv run pre-commit install
```

安装后，`git commit` 会自动执行 Ruff 和 mypy。hook 如果自动修改了文件，本次提交会停止；检查修改、重新暂存后再次提交即可。

GitHub Actions 会在 push、pull request 或手动触发时，使用 Python 3.13 和 `uv.lock` 重复运行格式检查、lint、mypy、测试与 coverage 报告。

## 环境变量

- `MODEL_ID`：必填，传给 Anthropic Messages API 的模型名称
- `ANTHROPIC_API_KEY`：正常使用 Anthropic API 时必填
- `ANTHROPIC_BASE_URL`：可选，自定义 Anthropic 兼容接口地址
- `MEMORY_QDRANT_LOCATION`：可选，Qdrant 本地路径或完整的 `http(s)://` 服务 URL；默认 `~/.mini-code-agent/qdrant`
- `MEMORY_QDRANT_COLLECTION`：可选，Memory collection 名称
- `MEMORY_MAX_TOKENS`：可选，Memory 提取模型的最大输出 token

环境变量通过 `python-dotenv` 从 `.env` 加载。不要提交包含真实密钥的 `.env`。

## 安全说明

- 项目仅面向可信的本地开发环境。
- `bash` 工具通过 `subprocess.run(..., shell=True)` 执行命令。当前 denylist 不是完整沙箱。
- 不要把当前 Web 应用或智能体接口直接暴露到公网。
- 文件工具通过 `safe_path()` 限制路径必须位于当前工作区。
- `write_file` 和 `edit_file` 可以修改工作区内的文件。
- 当前版本是可信本地单用户模式：没有登录、token 或多用户隔离，不能直接暴露到公网。
- 本地 Qdrant 模式适合单进程使用；Web 与 CLI 并发运行时建议配置共享 Qdrant 服务 URL。
- 连接本机 Qdrant 服务时，应使用完整 URL，并通过 `NO_PROXY` 避免 loopback 请求进入系统代理。
- Django 当前使用 `DEBUG = True` 等开发配置。

## 当前限制

- 没有流式模型输出。
- 没有登录、多用户或远程部署认证。
- Memory UPDATE/DELETE、MemoryEvent 接入和自动索引恢复仍未完成。
- 没有完整的工具调用轨迹可视化。
- `bash` 工具仅适用于可信环境。

## 路线图

- 添加流式 Web 和 API 响应
- 在需要远程部署时增加真正的认证和多用户隔离
- 添加工具调用轨迹可视化
- 完成 Memory 生命周期与索引恢复
- 继续扩展关键分支的测试覆盖率

## 许可证

本项目采用 [MIT License](LICENSE)。
