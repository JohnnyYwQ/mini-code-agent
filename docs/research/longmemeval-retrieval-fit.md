# LongMemEval 对 `Memory.recall()` 检索评测的适配结论

## 结论

**可以用，但不是把官方 JSON 直接交给现有 runner。** 需要一层很薄的 adapter，把 LongMemEval 的“会话 session + session 级相关标签”转成本项目可存储、可评分的 Memory Point。

对当前“只评 `Memory.recall()`”的职责边界，最合理的第一版是：

- 使用 `longmemeval_s_cleaned.json`，先做 **session-level retrieval**；
- 绕过 `Memory.add()` 和 LLM 提取，直接将每个 session 写入评测向量库；
- 真实调用 `Memory.recall()`；
- 用 `answer_session_ids` 作为相关性真值。

这会评估“当前混合检索能否从原始会话块中找到证据”，**不等于**评估完整 Memory 系统，也不等于评估 LLM 提取后的原子 Memory 质量。

## 官方数据能提供什么

LongMemEval 包含 500 个问题，覆盖信息提取、多 session 推理、知识更新、时间推理和拒答。论文把长期记忆系统分为 indexing、retrieval 和 reading 三个阶段，因此独立测 retrieval 是官方支持的用法。[论文摘要与任务定义](https://arxiv.org/html/2410.10813#S3)[记忆系统的三阶段定义](https://arxiv.org/html/2410.10813#S4.SS1)

每个实例都包含：

- `question_id`、`question_type`、`question`、`answer`、`question_date`；
- 对齐的 `haystack_session_ids`、`haystack_dates`、`haystack_sessions`；
- session 级证据标签 `answer_session_ids`；
- turn 级证据标签 `has_answer: true`。

字段含义和标签用途由[官方 README 的 Dataset Format](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/README.md#L72-L88)直接定义。

### 数据变体

| 变体 | 官方定义 | 对当前检索评测的价值 |
| --- | --- | --- |
| LongMemEval_S | 每题约 115k tokens、约 40 个 sessions，包含干扰 session | **首选**；可测试真正的候选区分与排序 |
| LongMemEval_M | 每题约 500 个 sessions | 适合后续做规模/压力评测，不适合先做快速回归 |
| LongMemEval_Oracle | 历史中只有证据 sessions | 不适合评估检索区分能力，可作 adapter 校验或 QA 上界 |

这些差异来自[官方数据变体说明](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/README.md#L74-L88)。当前官方下载页面提供清理后的 `longmemeval_s_cleaned.json`、`longmemeval_m_cleaned.json` 和 `longmemeval_oracle.json`。[官方下载指令](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/README.md#L34-L43)[官方 Hugging Face 数据集](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)

## 相关性标签如何映射

### 推荐的 session-level 映射

| LongMemEval | 本项目评测适配 |
| --- | --- |
| `question` | `Memory.recall(query=...)` |
| 一组 `haystack_sessions[i]` | 一个候选 Memory Point |
| `haystack_session_ids[i]` | 原始候选 ID；适配器将它稳定映射成 Qdrant UUID |
| `answer_session_ids` | 相关 session ID 集合，经同一 UUID 映射后评分 |
| `question_id` | 独立 `space_id`，保证每题只检索自己的 haystack |
| `question_type` | 分组报告标签 |
| `haystack_dates` / `question_date` | 暂存诊断元数据；当前 `recall()` 没有时间过滤入参 |

官方 flat session baseline 将一个 session 内的 **user-side messages 拼接成一个检索文档**；为了与官方 baseline 对齐，第一版 adapter 应使用相同表示。[官方 `process_item_flat_index`](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/src/retrieval/run_retrieval.py#L202-L229)

每个问题必须使用独立 space，否则把 500 题的历史混在同一检索域中，就改变了 LongMemEval 为每题定义的 haystack。可以共用一个固定评测 `user_id`，但不应写入 user-scope Memory。

### turn-level 可以做，但不应是第一步

`has_answer: true` 能提供 turn 级真值。官方实现仅将 user turns 编入索引，并可把 turn 级排名折算回 session 级。[官方 turn 索引逻辑](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/src/retrieval/run_retrieval.py#L211-L229)[turn-to-session 评分逻辑](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/src/retrieval/eval_utils.py#L32-L46)

但本项目生产 Memory Point 是 LLM 提取后的原子记忆，不是原始 turn。一个有证据的 turn 可能生成零个、一个或多个 Memory Point；LongMemEval 的 `has_answer` 不能自动判定这些提取结果中哪些相关。如果改为调用 `Memory.add()`，就已经从“独立 recall eval”扩展成“提取 + 检索”的端到端评测，需要额外的 provenance 和相关性标注规则。

## 官方检索指标

论文报告 `Recall@k` 与 `NDCG@k`。[论文 Memory Recall 小节](https://arxiv.org/html/2410.10813#S3.SS3.SSS2)

官方代码进一步定义了：

- `recall_any@k`：Top-k 中至少有一个证据项；
- `recall_all@k`：Top-k 包含全部证据项；
- `ndcg_any@k`：以二值相关性计算 NDCG。

定义见[官方 `eval_utils.py`](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/src/retrieval/eval_utils.py#L4-L29)。官方汇总脚本对 session 级主要打印 `recall_all@5`、`ndcg_any@5`、`recall_all@10` 和 `ndcg_any@10`。[官方汇总指标](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/src/evaluation/print_retrieval_metrics.py#L26-L40)

当前本项目 runner 的 `Recall@5 = |relevant ∩ top5| / |relevant|` 是“分数型 recall”，而官方主报的 `recall_all@5` 是“是否全部召回”的二值指标。两者不应同名或直接比较。`MRR@5` 可保留为本项目的诊断指标，但它不是 LongMemEval 官方主指标。

官方 retrieval 评测会跳过 `question_id` 以 `_abs` 结尾的 30 个拒答实例，因为它们没有可检索的真值位置；官方代码还会跳过没有 user-side target turn 的异常实例。[官方 README 的拒答说明](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/README.md#L184-L206)[官方跳过逻辑](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/src/retrieval/run_retrieval.py#L384-L410)

## 它不能替代当前手工用例

LongMemEval 是英文个人助手基准；每个实例只描述一个逻辑用户，没有跨 user/space 的 scope 标签。它不直接测试本项目的：

- `user_id` / `space_id` 跨边界隔离与 `ScopeLeakRate`；
- 中文、中英混合和代码工作流查询；
- LLM 记忆提取、去重、更新或失败链路；
- Agent 是否正确使用召回结果；
- 最终回答正确性。

此外，LongMemEval 有 `haystack_dates` 和 `question_date`，而当前 `Memory.recall()` 只接收查询、scope 和 limit。因此 temporal-reasoning 分组会真实暴露当前的“无时间感知检索”能力，但不能冒充时间过滤方案的评测。论文也将 time-aware query expansion 作为额外优化，而不是普通 flat retrieval 默认能力。[论文的时间检索分析](https://arxiv.org/html/2410.10813#S5.SS4)

## 建议的评测分层

1. **快速回归层**：保留现有小型手工用例，用于 scope、多语言和项目特定查询，适合每次提交运行。
2. **标准质量层**：增加 LongMemEval_S session-level adapter，用官方 labels 报告 `recall_all@5/10` 与 `NDCG@5/10`，并按 `question_type` 分组。
3. **规模层**：等 S 的 adapter 和指标稳定后，再跑 LongMemEval_M。

因此，LongMemEval 应当**补充而不是删除**现有 `cases.json`。前者提供大规模、标准化的语义检索压力；后者保护本项目独有的用户/工作区边界和真实代码助手场景。


python3 -c 'import os; from urllib.parse import urlsplit; u=urlsplit(os.environ["MINI_CODE_AGENT_PROXY_URL"]);
print("scheme=",u.scheme,"host=",u.hostname,"port=",u.port)'

proxy_port="$(python3 -c 'import os; from urllib.parse import urlsplit; print(urlsplit(os.environ["MINI_CODE_AGENT_PROXY_URL"]).port)')"
ss -lntp "sport = :${proxy_port}"

curl --silent --show-error --head --max-time 10 \
--proxy http://127.0.0.1:7897 \
https://files.pythonhosted.org/


ssh -NT \
-o ExitOnForwardFailure=yes \
-o ServerAliveInterval=30 \
-o ServerAliveCountMax=3 \
-R 127.0.0.1:7897:127.0.0.1:7897 \
ywq@10.107.236.173


curl --silent --show-error --head --max-time 10 \
    --proxy http://127.0.0.1:7897 \
    https://files.pythonhosted.org/


PYTHONDONTWRITEBYTECODE=1 \
/home/ywq/.local/share/mini-code-agent/venvs/cu124/bin/python \
-m unittest \
tests.memory.test_embedder \
tests.memory.test_candidate_stage

"$PY" - "$BASELINE" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))

print("qualification:", data["qualification"])
print("commit:", data["git"]["commit"])
print("git_clean:", data["git"]["clean"])
print("dataset:", data["dataset"]["stats"])

for name, report in data["reports"].items():
    m = report["overall"]
    print(
        name,
        f"RecallAll@5={m['recall_all@5']:.4f}",
        f"NDCG@5={m['ndcg_any@5']:.4f}",
        f"RecallAll@10={m['recall_all@10']:.4f}",
        f"NDCG@10={m['ndcg_any@10']:.4f}",
    )

print("E5 CUDA:", data["candidate_stage"]["runtime"]["e5_cuda_execution"])
print("BGE CUDA:", data["rerank_stage"]["runtime"])
PY