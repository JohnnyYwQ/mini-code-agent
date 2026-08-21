# Mini Code Agent 项目认知

> 这是一份随学习过程逐轮更新的认知文档，不是实现规范。当前进度：第 2 轮——Agent loop、LLM、tools 与三个消息视图。

## 一句话模型

这是一个面向可信本地环境的、单用户的 coding-agent harness：Django/CLI 负责接收请求和保存 Conversation，`AgentRuntime` 把完整消息历史、工具定义和临时 context 交给 Anthropic Messages API，并在模型要求调用工具时执行本地工具、回填结果、继续循环，直到模型不再返回 `tool_use`。

模型提供决策能力；本仓库实现的是它周围的 harness，不训练模型，也没有自研推理引擎。

## 两张互补的项目地图

项目需要同时用两种视角理解：

- **代码责任地图**：接入层、应用编排层、Agent Runtime、能力组件、持久化/外部系统；回答“代码放在哪里、谁调用谁”。
- **Agent 机制地图**：agent loop、LLM、tool runtime、context、Memory/RAG、skills、compaction、permissions/hooks、Conversation state；回答“模型如何持续行动、看见信息并影响世界”。

这些不是互斥分类。例如 Memory 同时是一个 Agent 机制，又横跨 runtime 接入、检索/提取逻辑和 Qdrant 基础设施。

本项目也没有一个单独对象能完整等同于“Agent”：运行中的 Agent 由外部 LLM 与本地 Agent Runtime、tools 和 context 共同构成；`chat/application.py` 只负责编排一个 Turn。

## 高层架构地图

```text
Web browser                         CLI
chat.js -> POST /api/chat/          cli.py -> prompt loop
          |                                   |
          +------------+----------------------+
                       v
             chat/application.py
   Conversation / Turn 编排与 SQLite transcript 持久化
                       |
                       v
              chat/composition.py
     装配 Anthropic client、Memory、workspace-bound runtime
                       |
                       v
             core/agent_runtime.py
      recall -> system context -> agent loop -> remember
            /          |             \
           v           v              v
  core/tooling.py compaction/skills/todo   core/memory/
  工具与 hooks       Turn 内 harness 状态    Qdrant + 提取/检索
           \           |              /
            +----------+-------------+
                       v
               Anthropic Messages API
```

模块责任：

| 模块 | 当前真实责任 | 不要误认为 |
| --- | --- | --- |
| `chat/views.py`、`chat.js` | Web 输入校验、HTTP/JSON 适配、显示最终文本 | Agent loop 本身 |
| `cli.py` | CLI adapter、Conversation 选择和终端输入输出 | Agent loop 本身 |
| `core/tooling.py` | 本地工具定义、handler 基础函数、权限策略和 hooks | CLI 或 Agent loop |
| `chat/application.py` | Conversation、Turn、workspace 和 transcript 的应用层编排 | LLM 或 Memory 算法层 |
| `chat/composition.py` | 为一个 Turn 装配 Anthropic client、共享 Memory 和 `AgentRuntime` | 业务状态存储 |
| `core/agent_runtime.py` | 当前真正的 agent loop；把 LLM、工具、context、Memory 接起来 | 常驻后台 Agent |
| `core/compaction.py`、`skills.py`、`todo.py` | context 压缩、按需技能、Turn 内 todo | 多 Agent/任务调度系统 |
| `chat/models.py` | SQLite 中的 MemorySpace、Conversation、ConversationMessage | Memory 内容存储 |
| `core/memory/` | Memory 提取、持久化、检索、重排 | Conversation transcript |

## 一次完整 Web 请求的真实调用链

### 0. 前置条件：Conversation 已存在

页面不是把一条孤立 prompt 直接交给 Agent。它先选中一个持久化 `Conversation`；Conversation 关联一个 `MemorySpace`，而该 Space 由 workspace path 定位。Web 新建 Conversation 时使用 Django 进程启动时的当前目录。

### 1. 浏览器发请求

`chat.js` 读取输入和 `conversation_id`，带 CSRF token 向 `/api/chat/` POST：

```json
{"conversation_id": "...", "message": "用户输入"}
```

当前接口非流式；浏览器只显示一个 `Thinking` 占位，等待整个 Turn 完成。

### 2. Django view 做协议适配

`chat.views.chat_api()` 校验 HTTP method、JSON、非空消息和 UUID，然后调用：

```python
run_conversation_turn(
    conversation_id=conversation_id,
    query=raw_message,
    runner_factory=build_web_runner,
)
```

view 不直接调用 LLM，也不执行工具。

### 3. application 层先建立可信运行边界，再保存用户消息

`run_conversation_turn()` 的顺序很重要：

1. `prepare_conversation_runtime()` 从数据库中的 Conversation 推导 workspace path 和 `MemoryContext(user_id, space_id)`，并确认 workspace 目录存在。
2. 先把规范化后的 user message 写入 SQLite。
3. 从 SQLite 重新加载该 Conversation 的全部顶层协议消息。
4. 调用 `runner_factory(runtime_context)` 构造本 Turn 的 runtime。

所以 Conversation 是持久的，但 `AgentRuntime` 是每个 Turn 新建的。

### 4. composition 装配 runtime

`build_web_runner()` 创建：

- 一个新的 Anthropic SDK client；
- 一个绑定当前 Conversation workspace 的 `AgentRuntime`；
- 进程内缓存、跨 Turn 复用的 production `Memory` 对象；
- 当前 Conversation 派生出的 `MemoryContext`；
- Web 的“破坏性操作一律拒绝”确认策略。

Memory 初始化失败时会降级为无 Memory runtime，而不是让整个 Agent 不可用。

### 5. runtime 准备本 Turn 的 context/state

`AgentRuntime.run()` 创建三个不同用途的消息集合：

- `model_messages`：发给模型的工作副本，会被压缩；
- `transcript`：本 Turn 使用的较完整副本，供统计和 `remember` 提取窗口使用；
- `generated`：只收集本 Turn 新生成的 assistant/tool-result 顶层消息，成功后交给 application 持久化。

三个 list 的生命周期都不超过这一次 `run()`；它们分开的原因是职责不同，不是生命周期不同：

| 时刻 | `model_messages` | `transcript` | `generated` |
| --- | --- | --- | --- |
| 进入 runtime | 数据库加载的全部历史，含当前 user message | 同一历史的独立副本 | 空 |
| compaction 后 | 可能被裁剪或替换成 summary | 保持较完整，不随之压缩 | 不变 |
| assistant 返回 | 追加 SDK response content | 追加 JSON-ready assistant | 追加同一条 JSON-ready assistant |
| tool 执行后 | 追加一个 user/tool-result 消息 | 追加同一 tool-result 消息 | 追加同一 tool-result 消息 |
| runtime 成功退出 | 丢弃 | 丢弃 | 返回 application，只持久化这些新增消息 |

如果合并成一个 list，compaction 会同时破坏 Memory 提取所需的较完整轨迹；application 也无法只提交本 Turn 的新增消息，容易重复保存旧历史或把临时 compact summary 当成正式 Conversation Transcript。

`transcript` 是内存变量；`.transcription/` 则是 compactor 在每次模型调用前写出的磁盘 JSONL 快照，两者不是同一个概念。

随后只在 Turn 开始时，用最新 user query 检索一次 Memory，并把结果格式化进临时 `system` 字符串。该 recalled context 不写进 ConversationMessage。

### 6. agent loop

每轮执行：

1. `ContextCompactor.prepare_for_model(model_messages)` 保存快照，并按预算裁剪/压缩模型工作副本。
2. 调用 `message_client.messages.create(...)`，显式传入 model、system、tools、完整 `model_messages` 和 max tokens。
3. 把模型的 assistant content 追加到三个相关消息集合。
4. 若 `stop_reason != "tool_use"`，把 `generated` 返回 application，Turn 的 loop 结束。
5. 否则逐个处理 response 中的 `tool_use` block：先过 permission hook，再调用 handler。
6. 把全部工具输出组装成一个 role=`user` 的 `tool_result` 消息，追加到消息集合，然后进入下一轮 LLM 调用。

核心闭环是：

```text
messages -> LLM -> assistant(tool_use) -> local tool
    ^                                      |
    +----------- user(tool_result) --------+
```

模型决定“调用哪个工具、参数是什么、什么时候停止”；Python loop 负责协议、权限检查、执行和回填。

### 7. 成功后提交 transcript，返回 UI

application 从 `generated` 的最后一个 assistant message 提取可见文本。只有存在最终可见文本时，才把本 Turn 的 assistant/tool-result 顶层消息批量写入 SQLite，并返回 `TurnResult`。view 把它序列化为 JSON，`chat.js` 替换 `Thinking` 占位。

### 8. 失败语义

- workspace 不存在：在保存 user message 前失败。
- LLM/runtime 在 user message 已保存后失败：数据库会保留未回答的 user message。
- 本 Turn 生成到一半后失败：中间 assistant/tool-result 不写入 SQLite。
- 但已执行的 shell/文件工具副作用、已写入的 Memory，以及 `.transcription`/`.tool_result` 文件不在数据库事务内，不能随 Turn 失败回滚。

最后一点是 demo harness 的真实边界，不能把“transcript 批量提交”讲成整个 Turn 具有事务性。

## 模块 1：接入层

接入层是外部协议与应用用例之间的 adapter。它把 Web/CLI 输入统一翻译为 `conversation_id + query`，调用 `run_conversation_turn()`，再把 `TurnResult` 或异常翻译回各自协议。

### Web 接入

- Django 根路由把 `/` 交给 `chat.urls`。
- `GET /` 的 `index()` 查询 Conversation 列表和选中会话的 transcript，只把字符串 user 内容和可提取的 assistant 文本投影到 HTML；assistant 的中间 tool-use preamble 只要含文本也可能显示，并不只限最终回复。tool-result、纯 tool-use 和 thinking 内容通常被隐藏。
- `POST /conversations/new/` 创建 Conversation 并重定向。没有选中旧 Conversation 时，workspace 使用 Django 进程启动时的当前目录。
- 浏览器 `chat.js` 在本地先显示 user message 和 `Thinking`，再带 CSRF token 同步等待 `POST /api/chat/` 的完整 JSON 响应。
- `chat_api()` 对不可信请求做语法与形状校验：method、JSON object、非空字符串 message 和合法 UUID。它不会因此信任字段的业务含义；User、Memory Space 和 workspace 等可信运行上下文由 application 从数据库 Conversation 推导。`AgentResponseError`（没有最终可见 assistant 文本）映射为 502；普通 LLM/runtime 异常当前落入通用 500。
- 成功响应只返回最终 assistant 文本；`tool_trace` 当前固定为空数组。没有 SSE、WebSocket 或 token streaming。

### CLI 接入

- `cli.py` 作为脚本运行时初始化 Django，可列出、恢复或新建当前 workspace 的 Conversation。
- 每次终端输入同样调用 `run_conversation_turn(..., build_cli_runner)`，再打印最终 assistant 文本。
- CLI 和 Web 从 application 层开始共用同一套 Conversation、runtime、tools 和 Memory；接入差异主要是 I/O、Conversation 选择范围和破坏性命令确认方式。

### 接入层明确不做什么

- 不直接调用 Anthropic API；
- 不构建 system prompt 或模型 messages；
- 不执行 tool handler；
- 不实现 Memory 检索/写入；
- 不决定 Agent 是否继续行动。

当前 Web 是单用户本地 demo：使用 CSRF，但没有产品级登录/多租户身份边界，也会让 HTTP 请求一直占用到整个 Agent Turn 结束。

## CLI 与 Web 在哪里汇合

CLI 只替换了最外层输入/输出和破坏性操作确认方式：它在 `cli.py` 中读取终端输入，然后同样调用 `run_conversation_turn(..., runner_factory=build_cli_runner)`。从 application 层开始，Conversation 持久化、runtime、LLM loop、tools 和 Memory 链路与 Web 相同。

## 当前状态分别放在哪里

| 状态 | 生命周期/存储 | 关键说明 |
| --- | --- | --- |
| Conversation transcript | SQLite，跨进程 | 保存 Anthropic 风格的顶层 user/assistant/tool-result 消息 |
| workspace/Space 关联 | SQLite，跨进程 | Conversation -> MemorySpace -> workspace path |
| Memory | Qdrant，跨 Conversation/进程 | 与 transcript 是两套存储；按 user/space scope 检索 |
| `model_messages` | 单 Turn 内存 | 每次 API 调用显式重发；可被 compaction 改写 |
| `transcript` | 单 Turn 内存 | runtime 的较完整工作副本，不等同于数据库事务 |
| `generated` | 单 Turn 内存 | 成功后才批量持久化的缓冲区 |
| recalled system context | 单 Turn 内存 | Turn 开始检索一次，所有 loop round 复用 |
| TodoManager | 单 Turn runtime 内存 | 下一 Turn 会新建，不是持久任务系统 |
| Skill registry | 单 Turn runtime 内存 | 每次 runtime 初始化时扫描当前 workspace 的 `.skills/` |
| 工具/压缩产物 | workspace 文件系统 | 可能早于 transcript 提交产生副作用 |

LLM API 本身不替项目保存会话状态；连续性来自本项目每轮显式发送 messages。

### Compaction 的准确顺序

每次普通 LLM 请求前，`prepare_for_model()` 依次执行：

1. 把调用前的 `model_messages` 快照写入 `.transcription/`；
2. `_tool_result_budget`：只检查最后一个 user tool-result 消息；其内容总量超过 12,000 字符时，优先把超过 4,000 字符的大结果落到 `.tool_result/`，消息中保留路径和预览；
3. `_snip_compact`：顶层消息数超过 100 时保留头部、尾部并插入一条 snipped 占位；默认不是 50 条，也不保证机械地保留固定 3+96 条，因为会避免切断 `tool_use`/`tool_result` 配对；
4. `_micro_compact`：只保留最近 8 个 tool result 的完整长内容，更早且超过 120 字符的结果替换为占位；
5. 用 `len(str(messages)) // 4` 粗估 token；超过 20,000 才调用 LLM 总结，并把工作历史替换为一条 `[Compacted]` user message。

这些操作只修改 `model_messages` 工作副本。SQLite Conversation Transcript 和 runtime 的 `transcript` 不会因此被同步覆盖。

## learn-claude-code 骨架与本仓库演进（高层）

由本地 Git 历史可确认：

- `514259b` 是最小版：一个 Anthropic `messages.create()` 循环、一个 bash 工具、`tool_use`/`tool_result` 回填。这就是 learn-claude-code 的核心模式。
- 后续早期提交逐步加入多工具、Todo、Django Web、权限 hooks、skills 和 context compaction；到 `25ce1d5` 已形成 memory 之前的主要 harness。
- `9e0076f` 首次加入 Qdrant/BM25 相关 Memory 基础。
- `1369ed4` 是主要结构分界：新增持久 Conversation/MemorySpace、application/composition 层、workspace-bound `AgentRuntime`，并把 scoped Memory 接入真实 Turn。
- `e29a807` 继续打磨 CLI/Conversation/Memory demo。
- `627c248` 以后主要增加 reranking、retrieval eval 和 LongMemEval/CUDA 评测设施。

因此不能简单说“原项目在 `agent.py`，我只加了一个 memory 文件夹”。为接入 Memory，本仓库同时重塑了 Conversation 生命周期、runtime 装配、消息持久化和 workspace/scope 边界。

注意：learn-claude-code 的当前上游已经继续增加新章节，其中也有自己的 Memory 课程模块；它不应倒推成本仓库当初的原始基线。本项目的改动边界应优先按本地提交历史判断。

## 明确的 demo / 非实现边界

当前确实没有：

- subagent 或多 Agent 调度；
- 后台任务、队列、cron、长期驻留的 Agent worker；
- MCP/plugin runtime；
- 持久化 Todo/task graph；
- token streaming；
- 工具副作用与 transcript/Memory 的统一事务；
- 面向不可信公网用户的 sandbox、认证、细粒度授权与并发治理。

现有 permission hook 是字符串 deny list + 少量路径检查，属于教学 demo 安全层，不是生产 sandbox。
`read_file`、`write_file`、`edit_file` 和 `glob` 有显式 workspace 路径约束；`bash` 仅把 workspace 设为子进程 `cwd`，shell 命令仍可访问 workspace 之外的路径。

## Memory 章节（待下一轮展开）

已确认与主链的两个接点：

1. Turn 开始时 `recall(latest_user_query)`，结果注入临时 system context；
2. loop 中模型主动调用无参数 `remember`，runtime 从最近可见 Turn 构建窗口并交给 `Memory.add()`。

提取、ADD/UPDATE/DELETE、Qdrant 表示、混合检索、重排、scope 过滤及与 mem0 的差异将在后续轮次逐层验证。

## 第一轮 Agent 面试追问

1. 为什么说 `AgentRuntime` 不是一个常驻 Agent？它的实例生命周期和 Conversation 生命周期分别是什么？
2. `model_messages`、`transcript`、`generated` 为什么不能合并成一个 list？
3. 如果一次 Turn 先写文件、再调用 `remember`、最后 LLM 报错，SQLite transcript、文件系统、Qdrant 各留下什么？
4. 谁决定工具调用，谁执行工具？`tool_result` 为什么使用 role=`user`？
5. Memory recall 为什么属于 system context，而 Conversation 历史为什么属于 messages？当前代码是否会在同一 Turn 内重新 recall？
