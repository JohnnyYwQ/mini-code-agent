# Mini Code Agent：Agent 开发简历素材

[返回项目首页](../README.md) · [架构](architecture.md) · [检索评测](memory-and-evaluation.md)

面向 Agent 开发岗位，重点展示运行时、Memory、上下文管理与评测工程。以下描述以当前代码为依据；个人负责范围和项目起止时间请按实际经历填写。

## 可直接用于简历的版本

**Mini Code Agent｜支持会话恢复与跨会话 Memory 的 Coding Agent**  
技术栈：Python、Django、Anthropic Messages API、Qdrant、FastEmbed、FlagEmbedding、SQLite、uv、GitHub Actions

项目描述：面向本地代码仓库构建 Coding Agent，提供 Web/CLI 双入口，支持工具调用、会话恢复、作用域 Memory 和上下文压缩，并配套独立的检索评测流程。

- 实现按 Turn 创建的 Agent Runtime，基于 `tool_use` / `tool_result` 编排模型与工具循环，集成文件、shell、todo、skills 等能力，处理工具异常、执行前权限检查和最大轮次限制。
- 设计 User Memory / Space Memory 两级作用域，由应用层注入可信身份；实现滚动窗口 Memory 提取、内容去重及 E5 + BM25 + RRF + BGE 混合检索，每轮最多召回 5 条相关 Memory，支持同工作区跨会话复用。
- 分离持久化 Conversation Transcript 与模型工作上下文，实现长工具输出落盘、历史裁剪及摘要压缩；用户消息先保存，成功运行的生成消息原子追加，并对 Memory 初始化与召回故障降级处理。
- 构建 LongMemEval-S 检索评测流程，将候选召回与 BGE 重排分进程执行，使用模型 revision、数据/源码摘要和参数绑定缓存，支持逐题中断恢复及 CUDA 执行校验；接入测试、类型检查与 CI。

简历篇幅紧张时保留前三条。若岗位强调检索、评测或推理工程，保留第四条，并缩短工具枚举。

## 可量化内容与使用条件

### 当前本地可核验

2026-09-06 在本地开发环境执行项目测试与覆盖率检查：

- 收集 159 项测试，158 项通过，1 项真实 E5 smoke 按默认配置跳过。
- `core` 与 `chat` 在当前 coverage 配置下的语句/分支综合覆盖率为 83%；不包含 CLI、评测脚本和 Django 配置的完整覆盖情况。
- Ruff 格式/静态检查和 mypy 通过；mypy 当前检查 `src/main/python/core` 的 20 个源文件。

可选补充句：

> 配置 Django tests、Ruff、mypy 与 GitHub Actions 质量检查；本地 158 项测试通过，核心 Agent/Memory 与会话应用模块语句/分支综合覆盖率达 83%。

这反映本次本地验证，不能据此声称远端 CI 已通过。测试以隔离依赖和模拟模型响应为主，不等同于真实模型任务成功率或正式 CUDA 全量评测。

复核命令：

```bash
uv run --locked coverage run src/main/python/manage.py test tests.chat tests.memory
uv run --locked coverage report -m
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy
```

真实 E5 smoke 由 `RUN_E5_SMOKE=1` 单独启用，需要模型缓存或下载，见[使用指南](usage.md)。

### 检索成绩：先补齐产物再放入正式简历

既有运行 `20260816-cu124-v1` 记录：419 个可评分样本，RecallAll@5 为 92.60%，NDCG@5 为 94.74%；相对 RRF，BGE 分别提升 1.91 和 2.57 个百分点。
正式 baseline、逐题记录和运行日志尚未在仓库发布并独立复核。上面的简历正文因此先描述已实现的评测能力。

产物取回、哈希与统计复核完成后，可将第四条改为：

> 在 LongMemEval-S 的 419 个可评分样本上完成 BM25、E5、RRF 与 BGE 重排对比，最终检索链 RecallAll@5 达 92.60%、NDCG@5 达 94.74%，较未重排 RRF 分别提升 1.91、2.57 个百分点；实现分阶段缓存、逐题恢复与 CUDA 执行校验。

面试展开时说明：源数据 500 题，排除 30 个 Abstention Case 与 51 个无 user-side 目标证据的样本；这些是检索排序指标，不是回答准确率。评测在固定 revision 上运行，也不能归因于后续的目录或文档调整。

## 每条亮点的实现证据

| 亮点 | 代码与验证入口 | 能解释的设计问题 |
| --- | --- | --- |
| Agent Runtime / Agent Loop | [agent_runtime.py](../src/main/python/core/agent_runtime.py)、[运行时测试](../src/test/python/tests/chat/test_agent_runtime.py) | 单轮运行状态如何与持久会话分离；工具结果如何返回模型 |
| 工具执行与权限 | [tooling.py](../src/main/python/core/tooling.py)、[工具测试](../src/test/python/tests/chat/test_tools.py)、[权限测试](../src/test/python/tests/chat/test_tool_policy.py) | 文件路径校验与 shell 工作目录各保证什么；Web/CLI 如何采用不同确认策略 |
| 会话持久化 | [application.py](../src/main/python/chat/application.py)、[models.py](../src/main/python/chat/models.py)、[应用测试](../src/test/python/tests/chat/test_application.py) | 为什么先保存用户消息，再原子追加成功生成的协议消息 |
| Memory 提取与作用域 | [extraction.py](../src/main/python/core/memory/extraction.py)、[memory.py](../src/main/python/core/memory/memory.py)、[写入测试](../src/test/python/tests/memory/test_memory_add.py) | 如何限制模型选择身份；多条写入部分失败时发生什么 |
| 混合检索与重排 | [memory.py](../src/main/python/core/memory/memory.py)、[qdrant_store.py](../src/main/python/core/memory/qdrant_store.py)、[召回测试](../src/test/python/tests/memory/test_memory_search.py) | dense 和 BM25 的分数为何通过排名融合；跨 Scope 如何去重 |
| 上下文压缩 | [compaction.py](../src/main/python/core/compaction.py)、[压缩测试](../src/test/python/tests/chat/test_compaction.py) | 工具输出预算、协议配对和持久 Transcript 如何兼容 |
| 评测与恢复 | [candidate_stage.py](../src/main/python/evals/memory_retrieval/candidate_stage.py)、[rerank_stage.py](../src/main/python/evals/memory_retrieval/rerank_stage.py)、[artifact_io.py](../src/main/python/evals/memory_retrieval/artifact_io.py) | 缓存何时可复用；如何避免跨问题 IDF 泄漏与无效 CUDA 结果 |
| 自动化检查 | [CI](../.github/workflows/ci.yml)、[工具配置](../pyproject.toml)、[测试目录](../src/test/python/tests/) | 哪些边界由单测覆盖，哪些仍需真实模型或硬件验证 |

## 面试展开顺序

1. **从一轮请求讲起。** Web/CLI 只做输入输出适配，应用层解析 Conversation 与工作区，Runtime 创建本轮执行状态，Agent Loop 处理模型/工具协议，最终由应用层持久化生成消息。
2. **解释两种状态。** Conversation Transcript 保存完整协议历史；Memory 是提取后可跨会话召回的信息。恢复同一个 Conversation 验证的是持久化，在同一工作区的新 Conversation 中召回才验证 Space Memory 复用。
3. **说明检索选择与代价。** E5 提供语义匹配，BM25 提供词项匹配，RRF 融合排名，BGE 在候选上重排；多阶段检索增加模型加载和推理开销。当前没有可支撑延迟降低或吞吐提升的性能数据。
4. **讲清失败边界。** 身份或工作区无效会阻止运行；Memory 故障允许降级；普通工具异常作为结果返回模型；运行失败不提交部分生成 Transcript，但已经执行的文件修改或 Memory 写入不会自动回滚。
5. **用评测检验取舍。** 解释 500/30/51/419 的样本口径、独立问题语料、固定候选池和缓存身份；BGE 只重新排序已有候选，不能补回第一阶段未召回的证据。

60 秒口述示例：

> 我做的是一个面向本地代码仓库的有状态 Coding Agent。我主要关注三件事：第一，基于工具调用协议实现 Agent Loop，并让每轮 Runtime 与持久化会话分离；第二，把完整对话历史和长期 Memory 分开，按用户与工作区确定作用域，再用 E5、BM25、RRF 和 BGE 完成召回；第三，用独立评测流程验证检索链，处理缓存恢复和实际 CUDA 执行校验。项目还有 Web/CLI 入口、上下文压缩和自动化检查。目前已实现 Memory 提取、写入与召回，完整运行轨迹和 Memory 更新删除仍是后续工作。

## 当前不应写成已实现的能力

- 多 Agent 协作、模型训练或微调：当前核心是单 Agent Runtime 与现成模型的推理集成。
- 生产级沙箱、多租户平台、高并发服务：当前只面向可信本地单用户；路径检查和权限 hook 有明确边界。
- 完整 Memory 生命周期、UPDATE/DELETE、Memory Event 历史和自动恢复：当前尚未完成。
- 完整可观测性平台或持久化运行轨迹：已有领域定义和设计决策，当前 API 的 `tool_trace` 仍为空，工具 hook 日志不等同于该能力。
- Token 成本下降百分比、响应耗时下降百分比或任务成功率：尚无对应的对照实验数据。
- Java / Spring Boot 项目：源码与运行栈是 Python/Django，目录布局不改变技术栈。
