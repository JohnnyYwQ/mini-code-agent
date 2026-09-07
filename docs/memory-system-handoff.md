# Memory System Handoff

## 1. 当前目标与闯关模式

- 项目根目录：`/Users/ywq/learn/mini-code-agent`。
- 固定分支：`feat/memory`。
- 总目标：在 Django 项目中实现一个可解释、可恢复、适合面试讲解的简化 Memory System；参考 Mem0，但按本项目的事实源、索引、事件历史和用户隔离需求重新设计。
- 当前最近目标：完成并验证 `QdrantStore.keyword_search()`，再逐颗测试补齐失败语义、空结果、`top_k` 和 scope filters。当前不要跳到 dense search、hybrid fusion 或 `Memory.add()`。
- 协作方式必须保持“闯关式”：
  1. 一次只解释一个很小的概念或调用链。
  2. 给多道理解题与固定答案题；用户答对后才进入下一小步。
  3. 实现采用纵向 TDD：确认 seam → 一颗红灯 → 用户解释 → 最小 green → 回归验证。
  4. 不一次倾倒大量架构或代码。用户的重点是能说明逻辑与 trade-off，不是练习手敲。

## 2. 已完成工作

- 当前 HEAD：`9e0076f add QdrantStore and BM25 encoder`。提交内容请直接查看 commit，不在本文件重复 diff。
- Django `MemoryEvent` model、migration 和生命周期测试已完成。可执行规格：
  - `config/core/memory/models.py`
  - `config/core/memory/migrations/0001_initial.py`
  - `config/tests/memory/test_memory_lifecycle.py`
- `QdrantStore` 的 collection 初始化与 `upsert()` 已完成：创建 unnamed dense/COSINE vector 与 named `bm25` sparse/IDF slot；兼容 collection 复用；dense-only collection 不自动迁移；不兼容 dimension/distance/named dense 会拒绝。
- 一个 memory 使用一个 Qdrant Point、一次 upsert，同时保存 dense vector、可选 BM25 sparse vector 和 payload。具体行为由 `config/tests/memory/test_qdrant_store.py` 约束。
- `FastEmbedBM25Encoder` 已完成：
  - `encode_document()` 使用底层 `model.embed()`。
  - `encode_query()` 使用底层 `model.query_embed()`。
  - 中文/中英混合在两条路径中都先经过注入的 Jieba segmenter；纯英文保持原文。
  - 预处理与 FastEmbed 输出到 Qdrant `SparseVector` 的转换已收进私有实现。
- 旧式 `encoder(text)`/`__call__()` 已移除；QdrantStore 通过明确的 `encode_document()` seam 调用。
- 已安装并锁定 memory 相关依赖：`qdrant-client`、`fastembed`、`jieba`；项目使用 Python 3.13 与 `uv`。
- 真实 BM25 smoke 曾通过：真实 FastEmbed BM25 + Jieba 能为中英文生成合法 sparse vectors，相关中文文本存在共享 token index。Jieba 0.42.1 在 Python 3.13 下可能打印旧正则 SyntaxWarning，这是已知依赖噪声。
- 在 keyword-search 改动前，`test_embedder` 与 `test_qdrant_store` 共 16 个测试通过，相关 Ruff 和 mypy 通过。

## 3. 当前代码结构与精确检查点

主要文件及职责：

- `config/core/memory/models.py`：已实现 `MemoryEvent`。
- `config/core/memory/embedder.py`：已实现 `FastEmbedBM25Encoder`。
- `config/core/memory/qdrant_store.py`：collection、upsert，以及当前未提交的 `keyword_search()` 实现。
- `config/core/memory/memory.py`：只有 `Memory` 方法草稿/docstrings，业务编排尚未实现。
- `config/core/memory/config.py`、`sqlite_store.py`、`extraction.py`、`llm.py`、`prompts.py`、`reranker.py`：仍为空。
- `config/tests/memory/test_qdrant_store.py`：collection/upsert 规格，以及 `QdrantStoreKeywordSearchTests`。
- `config/tests/memory/test_embedder.py`：document/query、中文预处理、模型空输出规格。
- `config/tests/memory/test_memory_add.py`、`test_memory_recovery.py`、`test_memory_search.py`：仍为空。

当前工作树的重要事实：

- `config/core/memory/qdrant_store.py` 有未提交修改；不要覆盖或回退。
- 该 diff 已给 `BM25Encoder` Protocol 增加 `encode_query()`，并实现：
  - 无 BM25 slot 或无 encoder → `None`。
  - 调用 `bm25_encoder.encode_query(query)`。
  - encoder 返回 `None` → `None`。
  - `client.query_points(..., using="bm25", limit=top_k)`。
  - 对外返回 `response.points`。
- 对应 happy-path 测试已经存在于 `QdrantStoreKeywordSearchTests.test_returns_bm25_matches_from_query_embedding`。
- 旧 handoff 记录的 `AttributeError: keyword_search 不存在` 已过期：方法现在已经写入，但本次 handoff 没有运行测试，因此必须标记为“已实现、尚未验证”，不能宣称 green。

## 4. 已确定的架构决策及原因

- 目标数据职责：未来 Django/SQLite memory record 是事实源；Qdrant 是可重建检索索引；`MemoryEvent` 是事实变更审计历史。当前只实现了事件表，memory fact-source model 尚未实现。
- embedding 不存入关系表；dense/sparse vectors 存在 Qdrant。payload 的 `data` 永远保留原始 memory text，Jieba 分词文本只在编码期间临时存在。
- Dense vector 使用 unnamed key `""`；BM25 sparse vector 使用 named key `"bm25"`。
- Dense embedding 由上层生成后传给 `QdrantStore.upsert()`；BM25 编码由 QdrantStore 持有的 encoder 完成。原因是 sparse slot 与 BM25 编码属于同一检索实现细节。
- 文档与查询必须区分：document → `embed()`，query → `query_embed()`。本地 Mem0 参考代码两侧都走 `embed()`，本项目明确不照搬该算法偏差。
- BM25 failure 不得阻断核心写入：upsert 捕获 BM25 编码异常并保存 dense-only。以后补 sparse index 仍使用同一 `memory_id`。
- Hybrid 最终必须覆盖 dense-only 与 dense+BM25 两类 Point：dense 分支检索全部，sparse 分支检索可用子集，之后按 `memory_id` 去重与融合。
- `keyword_search()` 自己不执行 dense fallback。已约定返回语义：
  - `None`：BM25 分支不可执行（无 slot、无 encoder、编码失败等）。
  - `[]`：BM25 查询成功但没有 hit。
  - `list[models.ScoredPoint]`：成功并有结果。
  - 上层未来的 `Memory.search()` 根据该结果决定 dense/hybrid 行为。
- 已有 Qdrant collection 不允许静默删除、重建或覆盖；dense-only collection 不自动补 BM25 slot。
- embedding 模型即使维度相同也未必兼容。更换模型应使用新 collection 或完整重建；模型身份/版本 metadata 校验尚未实现。
- 真实模型与 segmenter 应在装配阶段创建一次并注入、随后复用；不要在每次 add/search 中重新创建。Django 多进程可以每进程一份，不需要额外 worker manager。
- 用户/会话隔离必须由可信服务端身份生成 filters。当前无 filter 的 keyword happy-path 只是 tracer test，不是最终安全接口。

## 5. 不允许破坏的约束

- 写入前必须确认当前分支是 `feat/memory`。
- 保留所有现有/未提交用户改动，尤其是当前 `qdrant_store.py` diff；禁止 reset、checkout 覆盖或静默重写。
- 使用 `uv`；不要用 pip/conda。文件编辑使用 `apply_patch`。
- 不机械复制 Mem0 整个文件；复用思想和行为，保持 Django 项目的简化 seam。
- 不重新引入 `FastEmbedBM25Encoder.__call__()`；固定使用 `encode_document()` 与 `encode_query()`。
- query 不得走 `model.embed()`；必须走 `model.query_embed()`。
- 不覆盖 `payload["data"]` 原文，不把 Jieba 结果写回 payload。
- 不把 dense 与 sparse 拆成两次普通 upsert；主写入路径保持一个 Point、一次 upsert。
- 不让 BM25 失败阻断 dense 写入。
- 不混淆 `None` 与 `[]` 的 keyword-search 语义。
- 最终 search 必须带可信 scope filters，禁止跨用户/session 泄漏。
- `MemoryEvent.id` 是事件 ID，`memory_id` 是被操作 memory 的 ID；同一 memory 允许多条事件，历史保持从旧到新。
- 继续保持小步闯关；不要在一个 turn 同时实现 keyword failures、filters、dense、hybrid、reranker 和 Memory 编排。

## 6. 当前未完成事项

- 当前未提交的 `keyword_search()` happy-path 实现尚未验证。
- 当前实现没有捕获 `encode_query()` 抛出的异常；这与已约定“编码失败 → `None`”还不一致。
- 尚缺 keyword-search 的逐项测试：无 BM25 slot、无 encoder、encoder 返回 `None`、encoder 抛异常、成功零结果、`top_k`、Qdrant 查询异常，以及 metadata/scope filters。
- 尚无真实 dense embedder adapter，也没有 text → dense vector → Qdrant → dense query 的端到端语义 smoke；目前 dense vectors 均为测试手写。
- 尚无 dense search、hybrid union/fusion、按 `memory_id` 去重、分数融合/归一化或 reranker。
- `Memory` 的 add/update/get/delete/list/search 尚未实现。
- Django memory fact-source model、content hash、version、index_status（pending/ready/error）、soft delete 和 Qdrant 重建恢复流程尚未实现。
- `MemoryEvent` 尚未接入真实 Memory 生命周期。
- 尚无 production composition/factory 来创建并复用真实 dense model、BM25 model、Jieba、Qdrant client/store 与 Memory。

## 7. 下一步建议

1. 先让用户阅读当前 `keyword_search()` diff，并用闯关题确认调用链：
   - `keyword_search()` 是否调用了 `encode_query()`？
   - `query_points(query=...)` 收到原始字符串还是 `SparseVector`？
   - `using="bm25"` 的作用是什么？
   - 为什么返回 `response.points` 而不是整个 response？
2. 用户理解后，运行唯一目标测试：
   - `uv run python config/manage.py test tests.memory.test_qdrant_store.QdrantStoreKeywordSearchTests.test_returns_bm25_matches_from_query_embedding`
3. 若 green，运行 `test_embedder` + `test_qdrant_store` 回归，再运行相关 Ruff/mypy；不要重复实现 happy path。
4. 下一颗 TDD 优先测试 `encode_query()` 抛 `RuntimeError` 时 `keyword_search()` 返回 `None` 并记录 warning；当前代码预计会红，因为异常会向外传播。
5. 随后按一颗一颗顺序补：无 slot、无 encoder、encoder 返回 `None`、成功零结果、`top_k`。
6. 基础 keyword 行为稳定后，再单独设计 scope filters；不要把第一颗无 filter 测试当最终接口。
7. Keyword 链路闭环后才实现真实 dense embedder、dense search 与真实语义 smoke；两条链路都稳定后再做 hybrid fusion 和 reranker。
8. 最后回到 Django fact source、Memory 编排、事件与索引恢复。

## 8. 下一个会话优先阅读的文件

1. `docs/memory-system-handoff.md`。
2. `git diff -- config/core/memory/qdrant_store.py`：当前唯一已知未提交代码改动。
3. `config/tests/memory/test_qdrant_store.py`，优先看 `QdrantStoreKeywordSearchTests`，再看 collection/upsert tests。
4. `config/core/memory/qdrant_store.py`。
5. `config/core/memory/embedder.py` 与 `config/tests/memory/test_embedder.py`。
6. `config/core/memory/models.py`、migration 与 `test_memory_lifecycle.py`。
7. `config/core/memory/memory.py`，确认它仍是草稿。
8. 参考实现：`../mem0/mem0/vector_stores/qdrant.py`；注意 query 侧 `embed()` 问题，不要盲抄。
9. 后续编排阶段再读：`../mem0/mem0/memory/main.py` 与 `../mem0/mem0/memory/storage.py`。

## Suggested skills

- `$tdd`：当前 keyword-search 及后续 dense/search 生命周期继续使用一颗红灯一个 green 的节奏。
- `$codebase-design`：确定 `keyword_search` error modes、filters seam、dense/hybrid 分工时使用。
- `$domain-modeling`：进入 Django memory fact source、`MemoryEvent`、version/index status 等术语与 schema 时使用。
- `$diagnosing-bugs`：仅当 Qdrant local test、FastEmbed 或 Jieba 行为与预期不一致时使用；不要用它替代正常 TDD。
- `$code-review`：keyword-search milestone 或完整 memory branch 完成后，对照标准与规格做一次集中 review。
- `$handoff`：下个长会话结束时再次压缩最新状态，并覆盖本文件。
