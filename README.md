# Mini Code Agent

[English](README.en.md)

## 项目简介

Mini Code Agent 是一个用于学习和本地开发的小型 Django 编码智能体项目。它提供网页聊天界面、JSON 聊天接口和命令行入口，并通过 Anthropic Python SDK 调用 Claude Messages API。

智能体可以调用本地工具、读取工具结果并继续对话，直到模型返回最终回复。项目目前适合可信的本地开发环境，不适合直接部署到公网生产环境。

## 功能

- Django 网页聊天界面：`/`
- JSON 聊天接口：`/api/chat/`
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
├── requirements.txt
├── uv.lock
└── config/
    ├── manage.py
    ├── config/
    │   ├── settings.py
    │   ├── urls.py
    │   ├── asgi.py
    │   └── wsgi.py
    ├── chat/
    │   ├── tests/
    │   ├── templates/chat/index.html
    │   ├── static/chat/
    │   ├── urls.py
    │   └── views.py
    └── core/
        ├── agent.py
        ├── compaction.py
        ├── frontmatter.py
        ├── skills.py
        └── todo.py
```

关键文件：

- `config/core/agent.py`：Anthropic 客户端、智能体循环、工具定义、工具处理器、hook 和 CLI 入口
- `config/core/compaction.py`：会话快照、工具结果裁剪和上下文压缩
- `config/core/frontmatter.py`：解析 `SKILL.md` 的 YAML frontmatter
- `config/core/skills.py`：发现、注册和加载 skill
- `config/core/todo.py`：校验和维护 todo 状态
- `config/chat/views.py`：网页视图和 `/api/chat/` JSON 接口
- `config/chat/tests/`：单元测试和行为测试
- `pyproject.toml`：项目依赖和 Ruff、mypy、coverage 配置
- `uv.lock`：由 uv 生成的精确依赖锁文件
- `.github/workflows/ci.yml`：在 push、pull request 或手动触发时运行质量检查

`pyproject.toml` 和 `uv.lock` 是推荐的依赖管理入口。`requirements.txt` 暂时保留为兼容依赖列表，但它不是锁文件。

## 工作流程

1. 用户通过网页、JSON API 或 CLI 提交消息。
2. `UserPromptSubmit` hook 在消息进入模型前运行。
3. 上下文压缩器保存当前会话快照，并按需要裁剪或压缩历史。
4. `agent_loop()` 调用 Anthropic Messages API。
5. 如果模型返回 `tool_use`，对应的本地工具处理器会在 hook 检查后执行。
6. 工具输出作为 `tool_result` 添加到消息历史。
7. 循环继续，直到模型返回非工具调用的最终回复。
8. Web API 返回 JSON，CLI 将最终文本打印到终端。

Web 入口当前使用 `config/chat/views.py` 中进程级的 `AGENT_HISTORY`；CLI 入口使用 `config/core/agent.py` 中的本地 `history`。

## 快速开始

先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后在项目根目录同步锁定的依赖：

```bash
uv sync --locked
```

uv 会在项目根目录创建或更新 `.venv`。通常不需要手动激活虚拟环境，后续命令可以通过 `uv run` 执行。

创建本地环境变量文件：

```bash
cp .env.example .env
```

编辑 `.env`：

```env
MODEL_ID=your_model_id
ANTHROPIC_API_KEY=your_api_key
# ANTHROPIC_BASE_URL=
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
uv run python config/core/agent.py
```

输入 `q`、`exit`、空行、`Ctrl-C` 或 EOF 可以退出 CLI。

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
  -d '{"message":"hello"}'
```

## 开发检查

运行测试：

```bash
uv run python config/manage.py test chat
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
uv run coverage run config/manage.py test chat
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

环境变量通过 `python-dotenv` 从 `.env` 加载。不要提交包含真实密钥的 `.env`。

## 安全说明

- 项目仅面向可信的本地开发环境。
- `bash` 工具通过 `subprocess.run(..., shell=True)` 执行命令。当前 denylist 不是完整沙箱。
- 不要把当前 Web 应用或智能体接口直接暴露到公网。
- 文件工具通过 `safe_path()` 限制路径必须位于当前工作区。
- `write_file` 和 `edit_file` 可以修改工作区内的文件。
- Web 会话历史存储在进程内存中，并由当前 Django 进程共享。
- Django 当前使用 `DEBUG = True` 等开发配置。

## 当前限制

- 聊天和工具调用历史没有持久化到数据库。
- 没有流式模型输出。
- 没有用户账号和按用户隔离的会话。
- 没有完整的工具调用轨迹可视化。
- `bash` 工具仅适用于可信环境。

## 路线图

- 添加数据库会话和工具调用持久化
- 添加流式 Web 和 API 响应
- 添加用户账号和会话隔离
- 添加工具调用轨迹可视化
- 继续扩展关键分支的测试覆盖率

## 许可证

本项目采用 [MIT License](LICENSE)。
