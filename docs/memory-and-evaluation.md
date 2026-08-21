# Memory 与检索评测指南

[English](memory-and-evaluation.en.md) · [返回中文首页](../README.md) · [架构指南](architecture.md)

本文从产品中的作用域 Memory 一直说明到 LongMemEval Retrieval Baseline：Memory 如何产生与召回、评测如何构造检索语料与计分、已记录的正式结果意味着什么，以及怎样在固定 CUDA 主机上复现。

> **证据状态（2026-08-21）：** 下列 `20260816-cu124-v1` 指标与哈希是项目现有记录中的正式运行结果。该运行的 `baseline.json`、逐题记录和日志仍在固定 CUDA 主机上，尚未取回并发布到本仓库，也没有在当前工作站独立重新校验。这里不会把记录中的哈希描述为本次新验证的结果。

## 产品中的 Memory

### 所有权和边界

当前产品只服务一个可信本地 User。每个 Conversation 属于一个 Memory Space；在编码场景中，一个 Memory Space 对应一个规范化后的本地工作区。Application 先解析可信的 User、Conversation 和 Memory Space，再构造 Memory Context。Memory 只消费这个上下文，不能创建、切换或授权 Memory Space。

| 概念 | 可见范围 | 存储边界 |
| --- | --- | --- |
| User Memory | 同一 User 的所有 Memory Space | 只有 User ID，不带 Space ID |
| Space Memory | 一个 Memory Space 中的所有 Conversation | 同时带 User ID 和 Space ID |
| Scope | 一次操作允许访问的所有权范围 | 来自可信 Memory Context，不由模型指定身份 |
| Conversation Transcript | 一个 Conversation 的有序协议消息 | 是对话历史，不是 Memory |

Memory 是当前可检索的长期信息；Conversation Transcript 是 user、assistant、`tool_use` 和 `tool_result` 消息构成的权威历史。恢复同一个 Conversation 是重新加载 Transcript，不等于在另一个 Conversation 中召回 Space Memory。召回结果只是当前 Turn 的临时上下文，也不会写入 Transcript。

Qdrant Point 当前是 Memory 的权威当前状态并保存 Source Text。User Memory 与当前 Space Memory 会在搜索时合并；如果两个 Scope 中存在完全相同的 Source Text，返回 User Memory 并隐藏 Space 副本。当前版本还没有完整的 UPDATE、DELETE 和 Memory Event 历史链。

### 每个 Turn 的召回

在每个外层模型 Turn 开始前，Agent Runtime 使用最新用户查询和可信 Memory Context 调用 Memory recall：

1. 只搜索当前 User 的 User Memory 与当前 Memory Space 的 Space Memory。
2. 用 E5 dense 与 BM25 keyword 分别排序，再以 reciprocal-rank fusion（RRF）合并候选。
3. 默认使用 `BAAI/bge-reranker-v2-m3` 对候选重新排序，最多返回 5 条，并保留每条结果的 Scope 标签。
4. 将结果作为临时 system context 交给本 Turn；下一 Turn 会重新检索。

若可信身份或 Memory Space 解析失败，Turn 不会启动；若解析完成后检索基础设施失败，Agent Runtime 会记录错误并在没有 recalled Memory 的情况下继续。这一降级不会把失败的检索写入 Conversation Transcript。

### `remember` 写入流程

外层模型可在当前 Turn 调用无参数 `remember` 工具。模型不能提交 User ID、Space ID 或任意待保存文本；可信 handler 会提供 Memory Context，并组装最多 5 个已完成 Turn 加当前 Turn 中已有可见内容的滚动窗口。工具活动本身不参与提取。

提取模型一次处理整个窗口，可以输出零条或多条候选 Memory，并把每条分类为 User Memory 或 Space Memory。Memory 层复制可信身份；模糊内容必须选择较窄的 Space Scope，解析器不会静默补默认分类。全部候选先通过验证，随后逐条写入 Qdrant；写入不是跨多条 Memory 的事务，后续写入失败时，先前成功项仍然存在。`remember` 错误作为非致命工具结果返回，外层 Turn 可以继续。

产品链路的详细职责边界见[架构指南](architecture.md)，约束来源见 [ADR-0001](adr/0001-qdrant-as-current-memory-source.md)、[ADR-0002](adr/0002-user-and-space-memory-scopes.md)、[ADR-0006](adr/0006-retrieve-memory-for-each-turn.md) 与 [ADR-0007](adr/0007-extract-memory-from-a-five-turn-window.md)。

## LongMemEval 检索协议

### 语料与可评分样本

LongMemEval Retrieval Baseline 是独立的批量 Retrieval Evaluation Run，不读取或写入产品的持久化 Memory。它使用锁定的官方 cleaned LongMemEval-S 数据，并遵循官方检索实验的 session 粒度、user-only indexing、eligibility 和 `@5`/`@10` 计分规则。

每个问题都有独立的 haystack corpus，也使用独立的临时 Qdrant collection，避免 BM25 的集合级 IDF 在问题间泄漏。每个 haystack 数组位置都是一个独立的 Haystack Session Occurrence：即使两个位置使用相同 Source Session ID，它们在 dense、BM25、RRF 和 BGE 排序中仍是两个候选。只有在指标边界才把 occurrence 映射回数据集的 Source Session ID，与 Evidence Session 标签比较。

500 个源样本按以下口径进入聚合结果：

| 分类 | 数量 | 处理方式 |
| --- | ---: | --- |
| 源样本 | 500 | 锁定数据集的全部问题 |
| Abstention Case | 30 | 没有 Evidence Session，保留排除原因但不计入正向检索指标 |
| 无 user-side 目标证据 | 51 | 目标证据只在 assistant 文本等位置；user-only 协议无法对其计分 |
| 可评分样本 | 419 | `500 - 30 - 51`，进入聚合 Recall 与 NDCG |

六种可评分题型是 single-session-user、single-session-assistant、single-session-preference、multi-session、temporal-reasoning 和 knowledge-update。题型名称不改变 user-only 语料规则；例如 single-session-assistant 只有在目标 session 的 user 文本也标有证据时才符合检索 eligibility。

### Candidate Retrieval Stage

第一阶段对每个问题的完整独立 haystack 生成排名：

- E5：锁定的 `intfloat/multilingual-e5-base`，文档加 `passage: `、查询加 `query: `，mean pooling 并归一化。
- BM25：锁定的 `Qdrant/bm25`，keyword 排名独立于 dense 排名。
- RRF：用 rank constant 60 融合 E5 与 BM25；物化 top 50 候选。

候选 JSONL 与 completed-case ledger 是持久的 Evaluation Cache 和恢复边界，临时 Qdrant collection 不是。缓存身份包含数据集与问题 ID、模型 revision、top 50、RRF 60、E5 batch size 8、依赖、`uv.lock` 和相关源文件摘要。

### Reranking Stage

候选阶段完成并释放 E5 资源后，第二个进程加载 BGE，以 FP16 在 `cuda:0` 上对固定的 RRF top-50 pool 重排。默认 BGE batch size 为 4，最大输入长度为 512。该阶段不能扩展候选池；因此结果变化只反映对同一候选集合的排序。

正式报告同时保留四条 pipeline，方便定位收益来源：

1. BM25
2. E5
3. E5 + BM25 + RRF
4. E5 + BM25 + RRF + BGE

阶段拆分与官方协议分别由 [ADR-0013](adr/0013-separate-candidate-retrieval-from-bge-reranking.md) 和 [ADR-0014](adr/0014-follow-the-official-longmemeval-retrieval-protocol.md) 约束。ADR-0014 已取代早期同时索引 user 与 assistant 的 ADR-0011；公开主结果只使用 user-only 口径。

## 已记录的正式结果

### Pipeline 对比

`20260816-cu124-v1` 被记录为一次 `formal` / `full` Retrieval Evaluation Run，聚合 419 个可评分样本：

| Retrieval pipeline | RecallAll@5 | NDCG@5 | RecallAll@10 | NDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 87.35% | 89.33% | 92.12% | 90.44% |
| E5 | 90.93% | 89.92% | 95.94% | 91.20% |
| E5 + BM25 + RRF | 90.69% | 92.17% | 96.42% | 93.26% |
| E5 + BM25 + RRF + BGE | **92.60%** | **94.74%** | **97.61%** | **95.69%** |

最终链在四项主指标上最高。相对 RRF，BGE 链分别提升 1.91、2.57、1.19 和 2.42 个百分点。记录还显示最终链 RecallAny@10 为 100%，但 RecallAll@10 仍有 10 题未召回全部 Evidence Session：7 题 multi-session，3 题 temporal-reasoning。这提示后续工作应优先改善多 session 覆盖和时间关系检索。

> 这些数字仅是本项目 retriever 在锁定数据和协议上的检索证据，不是端到端 LongMemEval QA 分数、官方 leaderboard 结果，也不能推出通用 Agent 性能。

### 运行身份与参数

| 字段 | 已记录值 |
| --- | --- |
| Run ID | `20260816-cu124-v1` |
| Selection / qualification | `full` / `formal` |
| 源 revision | `7b1f9466f3f334bc9f6b58225397c3daee55dbd5` |
| Worktree qualification | 生成 baseline 时记录为 clean；runner 只有 clean worktree 才标记 `formal` |
| 数据集 | official cleaned LongMemEval-S，revision `98d7416c24c778c2fee6e6f3006e7a073259d48f`，文件 `longmemeval_s_cleaned.json` |
| Candidate 参数 | top 50；RRF constant 60；E5 batch size 8；每问题独立 corpus |
| BGE 参数 | input RRF；batch size 4；max length 512；FP16；`cuda:0` |

| 模型 | 锁定 revision |
| --- | --- |
| `intfloat/multilingual-e5-base` | `d128750597153bb5987e10b1c3493a34e5a4502a` |
| `Qdrant/bm25` | `e499a1f8d6bec960aab5533a0941bf914e70faf9` |
| `BAAI/bge-reranker-v2-m3` | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |

### CUDA 与 provider 验证

正式入口只接受 Ubuntu 20.04 x86_64、Python 3.13、单张 NVIDIA GeForce RTX 2070 SUPER 8 GiB、NVIDIA driver 550.142、PyTorch 2.6.0+cu124 和 CUDA 12.4。环境由同一份 `uv.lock` 的 `cuda-eval` extra 构造；普通 CPU 开发依赖与 CUDA 依赖被声明为冲突选择。

预检要求 ONNX Runtime 暴露 `CUDAExecutionProvider`，并用一次真实 E5 embedding profile 证明计算密集型算子位于 CUDA、没有计算密集型算子落到 CPU。provider 列表中仍可能包含处理 shape/control 节点的隐式 CPU provider，这不等于模型静默回退。BGE 必须在 `cuda:0` 以 FP16 执行，并记录参数所在设备。验证规则见 [ADR-0009](adr/0009-pin-retrieval-evaluation-to-one-cuda-host.md)、[ADR-0010](adr/0010-use-native-uv-for-cuda-retrieval-evaluation.md) 和 [ADR-0012](adr/0012-require-cuda-for-dense-encoding-and-reranking.md)。

### 哈希与证据可用性

| 项目 | 当前记录 | 当前状态 |
| --- | --- | --- |
| 数据集 SHA-256 | `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442` | 下载器会校验；本次文档工作只核对了代码中的锁定值，没有重新下载数据 |
| `full/baseline.json` SHA-256 | `e267d5696e37a0c006d354c5b21ca5bb8f2620f9a48dbdf5a881f1d6b18b9a34` | 来自既有项目记录；本地缺少文件，尚未重新计算 |
| Formal baseline | 尚未在仓库发布 | 不能从当前 clone 点击检查 |
| 逐题 JSONL 与 manifests | 尚未在仓库发布 | 仍待从固定 CUDA 主机取回 |
| smoke/full 日志与环境清单 | 尚未在仓库发布 | 仍待取回并检查敏感路径后发布 |

后续证据 ticket 的明确集成 seam 是 `docs/evidence/longmemeval/20260816-cu124-v1/`：取回后应先在隔离暂存位置重算 SHA-256，确认 baseline 与上述记录一致，再发布紧凑 baseline、manifests 和环境元数据；大体积逐题记录或日志若不适合进入 Git，应提供稳定的版本化下载地址与哈希。校验完成前，README 和本指南都不应把缺失文件链接包装成已发布证据，也不应为适配未知产物而修改记录值。

## 复现流程

### 下载与本地 smoke

下载器锁定数据集 revision、文件大小和 SHA-256；已有文件也会重新检查大小与摘要：

```bash
uv run --locked python \
  config/evals/memory_retrieval/download_longmemeval.py
```

普通开发环境可以先跑 10 个可评分样本，验证 adapter 与检索入口。它不是正式 CUDA baseline：

```bash
uv run --locked python config/evals/memory_retrieval/run.py \
  --longmemeval config/evals/memory_retrieval/data/longmemeval_s_cleaned.json \
  --max-cases 10 \
  --reranker none \
  --reranker bge
```

### 固定 CUDA 主机的 smoke 与全量运行

在符合固定 profile 的主机和 clean checkout 上，从仓库根目录执行：

```bash
export MINI_CODE_AGENT_RUN_ID=your-run-id
./scripts/run_longmemeval_cu124.sh
```

仅在下载需要代理时设置 `MINI_CODE_AGENT_PROXY_URL`。脚本要求至少 40 GiB 可用空间，校验/增量同步专用 Python 3.13 环境，验证 GPU、依赖、数据集和模型 snapshot，然后依次执行：确定性的 8-case smoke Candidate Retrieval Stage、smoke BGE Reranking Stage、419-case full Candidate Retrieval Stage、full BGE Reranking Stage。smoke 覆盖六种计分题型、一个 assistant-only 排除样本和一个 Abstention Case。

不要为正式结果设置 `MINI_CODE_AGENT_ALLOW_DIRTY=1`；该选项仅用于调试，并让 baseline 标记为 `provisional`。

### 缓存、恢复与产物

默认目录位于 `~/.local/share/mini-code-agent/eval/`：`cache/candidates/` 和 `cache/rerank/` 保存按内容寻址的阶段缓存，`runs/<RUN_ID>/` 保存本次 smoke/full manifests、baseline、环境清单与日志。脚本会复用完整的固定 revision 模型 snapshot；缺失时只下载所需文件。

运行中断后，使用完全相同的数据集、代码、锁文件、参数与 `MINI_CODE_AGENT_RUN_ID` 再次执行同一脚本。Candidate Retrieval Stage 与 Reranking Stage 会读取 JSONL completed-case ledger，从已完成问题之后继续；身份变化会产生不同 cache key，不会把不兼容记录混入结果。`run.lock` 防止两个 CUDA run 同时写同一 evaluation home。

成功后重点检查：

```text
runs/<RUN_ID>/full/baseline.json
runs/<RUN_ID>/full/candidate-stage.json
runs/<RUN_ID>/full/rerank-stage.json
runs/<RUN_ID>/environment.txt
runs/<RUN_ID>/git-status.txt
runs/<RUN_ID>/full-candidates.log
runs/<RUN_ID>/full-rerank.log
```

发布 Retrieval Baseline 前，确认 `selection=full`、`qualification=formal`、git commit 与 clean 状态、500/30/51/419 统计、三个模型 revision、阶段参数、CUDA runtime/provider 证据和数据集摘要，再独立计算待发布文件的 SHA-256。

## 限制与解读

- 评测只测试检索排序，不运行 reader LLM、生成答案或答案 judge。
- user-only 官方口径故意不衡量 assistant-side retrieval coverage；51 个无 user-side 证据样本被排除，而不是记为检索失败。
- Abstention Case 需要“不从无支持上下文作答”的系统行为；当前检索契约没有拒答输出，因此不计入正向 Recall/NDCG。
- baseline 使用官方数据、eligibility 与公式，但 retriever 是本项目的 E5/BM25/RRF/BGE 链，不是官方仓库的 retriever，也不是官方 leaderboard submission。
- 结果只代表固定数据、代码 revision、模型 snapshot、参数与 CUDA profile；不能外推到一般 Coding Agent 任务。
- 正式产物尚未本地发布和独立复核，是当前证据链最重要的缺口；在补齐前，应将结果称为“已记录”，而不是“已在仓库验证”。
