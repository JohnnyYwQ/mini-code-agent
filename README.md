# Mini Code Agent

一个最小可运行的 code-agent Web 应用骨架。

当前版本的重点不是做完整 Claude Code，而是把 agent harness 的关键边界先落下来：

- `BaseTool.call()` 固定工具生命周期：`validate -> check_permission -> run -> format_result`
- `build_tool_registry()` 统一注册模型可调用工具
- `core.agent.run_agent_turn()` 统一处理 Claude Messages API、tool_use、tool_result 和多轮工具调用
- Django chat 页面只做薄壳，展示用户消息、助手消息和工具调用轨迹

## Run

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env
python3 config/manage.py migrate
python3 config/manage.py runserver
```

CLI 入口也使用同一个 core：

```bash
python3 agent.py
```

## Structure

```text
agent.py                 # CLI thin wrapper
config/core/agent.py     # agent loop / model runtime
config/core/tools.py     # BaseTool and concrete tools
config/chat/views.py     # Django thin chat shell
config/chat/models.py    # future DB persistence shape
```

## Current Tool Set

- `bash`: 在 workspace 内执行 shell 命令
- `read_file`: 读取 workspace 内文本文件
- `write_file`: 写入 workspace 内文本文件
- `edit_file`: 对 workspace 内文本文件做精确替换
