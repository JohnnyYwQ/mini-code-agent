# Mini Code Agent

[English](README.en.md) · [使用指南](docs/usage.md) · [测评详情](docs/memory-and-evaluation.md)

[![CI](https://github.com/JohnnyYwQ/mini-code-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/JohnnyYwQ/mini-code-agent/actions/workflows/ci.yml)
![Python 3.13+](https://img.shields.io/badge/Python-3.13%2B-3776AB)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**通过网页或终端使用的本地代码助手。**

让 Agent 帮你阅读和修改代码、执行命令，并继续之前的会话。可选的跨会话 Memory 能记住你的偏好和项目约定。

> 适合在可信的本地项目中个人使用。Agent 可以修改文件、执行命令，请勿将服务暴露到公网。

## 快速开始

准备 Python 3.13+、[uv](https://docs.astral.sh/uv/getting-started/installation/)，以及 Anthropic API 或兼容服务的模型名称和 API Key。

### 1. 安装

```bash
git clone https://github.com/JohnnyYwQ/mini-code-agent.git
cd mini-code-agent
uv sync --locked
cp .env.example .env
```

### 2. 配置

编辑 `.env`，将占位内容替换成你的模型名称和 API Key。使用兼容服务时，取消 `ANTHROPIC_BASE_URL` 的注释并填写服务地址。

```env
MODEL_ID=your_model_id
ANTHROPIC_API_KEY=your_api_key
MEMORY_ENABLED=false
# ANTHROPIC_BASE_URL=
```

先保持 `MEMORY_ENABLED=false`，无需下载 Memory 模型即可聊天；会话历史仍会保存。不要提交包含 API Key 的 `.env`。

### 3. 启动

首次使用时，无论选择网页还是 CLI，都先初始化数据库：

```bash
uv run --locked python src/main/python/manage.py migrate
```

启动网页：

```bash
uv run --locked python src/main/python/manage.py runserver
```

打开 [http://127.0.0.1:8000/](http://127.0.0.1:8000/)，点击 **New conversation**，输入消息并点击 **Send**。可以先试试：“查看当前项目，告诉我它的用途和运行方法。”

已有会话会显示在侧栏中，点击即可继续。

## 在终端使用

完成上面的安装、配置和数据库初始化后，也可以直接启动 CLI：

```bash
uv run --locked python src/main/python/cli.py
```

列出当前项目的会话，再用对应的 UUID 恢复会话：

```bash
uv run --locked python src/main/python/cli.py --list
uv run --locked python src/main/python/cli.py --resume <conversation-uuid>
```

将 `<conversation-uuid>` 替换为列表中的 UUID。输入 `exit` 或按 `Ctrl-C` 退出。

要处理其他项目，从目标项目目录启动 CLI：

```bash
cd /path/to/workspace
uv run --project /path/to/mini-code-agent \
  python /path/to/mini-code-agent/src/main/python/cli.py
```

将示例路径替换为实际路径。Agent 会在当前项目中操作文件和执行命令。

## 开启跨会话 Memory（可选）

将 `.env` 中的 `MEMORY_ENABLED` 改为 `true`，然后重启 Web 或 CLI。

首次使用需要下载额外模型，请准备可用的下载网络和数 GB 磁盘空间，首条回复可能需要等待。如果只想先使用代码助手，保持 `false` 即可。已有 `.env` 的用户需要手动添加这个设置。

更多配置、常见问题和开发命令见[使用指南](docs/usage.md)。

## 测评结果

LongMemEval-S 记忆检索测评，计分样本 **419 个**：

| 检索方案 | RecallAll@5 | NDCG@5 | RecallAll@10 | NDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| E5 + BM25 + RRF + BGE | **92.60%** | **94.74%** | **97.61%** | **95.69%** |

以上来自既有运行记录 `20260816-cu124-v1`，完整测评产物尚未在仓库发布并独立复核。指标衡量记忆检索效果，不等同于回答正确率或官方榜单成绩。[测评口径、完整对比与复现方法 →](docs/memory-and-evaluation.md)

## 更多文档

- [使用与贡献指南](docs/usage.md)
- [Memory 与测评详情](docs/memory-and-evaluation.md)
- [架构指南](docs/architecture.md)

## 致谢与许可证

早期 Agent Loop 思路受 [shareAI-lab/learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) 启发。

[MIT License](LICENSE) © 2026 JohnnyYwQ
