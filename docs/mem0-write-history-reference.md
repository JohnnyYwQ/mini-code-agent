# Mem0 OSS 写入与历史实现参考

调研时间：2026-08-11。

参考范围：本地 Mem0 checkout `38e47ac2619b625ead46733db081251087f0c64b`（工作区有未提交修改），以及官方 `main` 在调研时的提交 [`4debc58a83377b18be81ae1e5969a300736b2fac`](https://github.com/mem0ai/mem0/tree/4debc58a83377b18be81ae1e5969a300736b2fac)。下面涉及的核心写入顺序在两者中一致。文中“事实源”是根据代码的读写路径作出的架构判断；Mem0 源码没有直接用这个术语声明。

## 结论摘要

Mem0 OSS 把 vector store 中的记录作为当前 Memory 的操作性事实：`get`、`get_all`、`search`、`update` 和 `delete` 都先从 vector store 读取当前 Point；SQLite `history` 表是旁路历史记录，不参与当前 Memory 的读取。[本地 `get`/`search` 实现](/Users/ywq/learn/mem0/mem0/memory/main.py:1096)，[官方 `get` 实现](https://github.com/mem0ai/mem0/blob/4debc58a83377b18be81ae1e5969a300736b2fac/mem0/memory/main.py#L1096-L1138)

它采用的是顺序双写，而不是跨库事务：

```text
先修改 vector store
        ↓
再向 SQLite 写成功历史
```

因此 Mem0 本身也存在“vector store 已成功，但 history 失败”的部分成功窗口。单条 create/update/delete 会把 history 异常继续抛给调用者，但不会回滚已经完成的 vector 操作，也没有内置重试。[官方 create](https://github.com/mem0ai/mem0/blob/4debc58a83377b18be81ae1e5969a300736b2fac/mem0/memory/main.py#L1778-L1807)，[官方 update](https://github.com/mem0ai/mem0/blob/4debc58a83377b18be81ae1e5969a300736b2fac/mem0/memory/main.py#L1843-L1890)，[官方 delete](https://github.com/mem0ai/mem0/blob/4debc58a83377b18be81ae1e5969a300736b2fac/mem0/memory/main.py#L1899-L1921)

## 1. 当前 Memory 存在哪里

当前 Memory 保存在配置的 vector store 中。以 Qdrant adapter 为例，一个 Point 由 ID、dense vector、可选的 `bm25` sparse vector，以及 payload 组成；payload 的 `data` 字段保存 Memory 文本。Qdrant 的 insert 最终调用 `upsert`。[本地 Qdrant insert](/Users/ywq/learn/mem0/mem0/vector_stores/qdrant.py:186)

SQLite manager 只创建两张表：

- `history`：Memory 的 ADD/UPDATE/DELETE 历史；
- `messages`：每个 session scope 最近的消息上下文。

它没有当前 Memory 表。[本地 SQLite schema](/Users/ywq/learn/mem0/mem0/memory/storage.py:102)，[官方 SQLite schema](https://github.com/mem0ai/mem0/blob/4debc58a83377b18be81ae1e5969a300736b2fac/mem0/memory/storage.py#L92-L137)

所以，和 mini-code-agent 当前设想最接近的参考结论是：

```text
vector store Point = 当前 Memory
SQLite history     = 已发生操作的历史副本
```

## 2. 精确写入顺序

### 单条 ADD（包括 `infer=False` 路径）

1. 对文本生成 embedding；
2. 生成新的随机 `memory_id`；
3. 构造 payload：`data`、`hash`、`created_at`、`updated_at`、`text_lemmatized` 及 scope/metadata；
4. `vector_store.insert(...)`；
5. `db.add_history(..., event="ADD")`；
6. 返回 `memory_id`。

本地代码：[raw add 调用](/Users/ywq/learn/mem0/mem0/memory/main.py:850)，[`_create_memory`](/Users/ywq/learn/mem0/mem0/memory/main.py:1932)。官方代码：[raw add](https://github.com/mem0ai/mem0/blob/4debc58a83377b18be81ae1e5969a300736b2fac/mem0/memory/main.py#L800-L830)，[`_create_memory`](https://github.com/mem0ai/mem0/blob/4debc58a83377b18be81ae1e5969a300736b2fac/mem0/memory/main.py#L1778-L1807)。

### UPDATE

1. `vector_store.get(memory_id)` 读取当前 Point；
2. 以当前 payload 为底，合并允许修改的 metadata；scope identity 字段不可通过 update 改写；
3. 如文本变化，生成新 embedding；
4. `vector_store.update(...)` 覆盖当前 vector/payload；Qdrant full update 使用同 ID `upsert`；
5. `db.add_history(old_memory, new_memory, "UPDATE")`；
6. history 成功后才进行非关键的 entity-store 清理/重建。

本地代码：[public update 与 `_update_memory`](/Users/ywq/learn/mem0/mem0/memory/main.py:1786)。官方代码：[`_update_memory`](https://github.com/mem0ai/mem0/blob/4debc58a83377b18be81ae1e5969a300736b2fac/mem0/memory/main.py#L1843-L1898)。

### DELETE

1. `vector_store.get(memory_id)` 读取旧 Point；
2. 保存旧文本和时间信息到局部变量；
3. `vector_store.delete(memory_id)`；
4. `db.add_history(old_memory, None, "DELETE", is_deleted=1)`；
5. history 成功后才做非关键 entity-store 清理。

本地代码：[public delete 与 `_delete_memory`](/Users/ywq/learn/mem0/mem0/memory/main.py:1840)，[官方 `_delete_memory`](https://github.com/mem0ai/mem0/blob/4debc58a83377b18be81ae1e5969a300736b2fac/mem0/memory/main.py#L1899-L1926)。

### HISTORY 读取

`Memory.history(memory_id)` 不访问 vector store，只调用 SQLite 的 `get_history(memory_id)`。[本地 history](/Users/ywq/learn/mem0/mem0/memory/main.py:1917)，[官方 history](https://github.com/mem0ai/mem0/blob/4debc58a83377b18be81ae1e5969a300736b2fac/mem0/memory/main.py#L1765-L1777)

## 3. 失败、回滚、重试与部分成功

### 单条 create/update/delete

源码没有包裹 vector 操作和 history 操作的共同事务，也没有补偿删除/恢复逻辑：

| 失败位置 | 可观察结果 |
|---|---|
| embedding 失败 | vector 和 history 均未写；异常上抛 |
| vector 写失败 | history 不执行；异常上抛 |
| vector 写成功、history 写失败 | 当前 Memory 已改变，history 缺失；SQLite 自己回滚该次 INSERT 后异常上抛 |
| entity-store 后处理失败 | helper 吞掉并记录日志，不破坏主 Memory 操作 |

这里“异常上抛”不等于整个操作回滚。特别是 history 失败时，调用者收到失败，但 vector store 已经改变。代码没有返回专门的 partial-success 类型，也没有把已写入的 `memory_id` 附在异常中。

代码中也没有针对这三条单操作路径的 retry/backoff。若调用者自行重试：

- 重试 ADD 会生成新的 `memory_id`，可能产生重复 Memory；
- 重试 UPDATE 会再次覆盖同一 ID，并再生成一条 history；
- DELETE 已成功但 history 失败后，重试 DELETE 会因 Point 已不存在而失败，无法自动补齐 DELETE history。

### `infer=True` 批量 ADD 是一个更弱的特例

官方当前实现先 batch insert；失败后逐条 insert，但逐条失败只记录日志。随后它会为最初构造的全部 records 写 history；history batch 失败后也逐条 fallback，并再次吞掉逐条失败。最后返回值仍由全部 records 构造。[官方 batch persist/history](https://github.com/mem0ai/mem0/blob/4debc58a83377b18be81ae1e5969a300736b2fac/mem0/memory/main.py#L947-L984)，[官方返回结果](https://github.com/mem0ai/mem0/blob/4debc58a83377b18be81ae1e5969a300736b2fac/mem0/memory/main.py#L1081-L1095)

这意味着代码允许：

- Point 插入失败，但仍写出 ADD history；
- history 写失败，但仍返回该 Memory 的 ADD 成功结果；
- 一批 records 部分成功，但调用者拿不到逐项可靠状态。

这更像“尽力批处理”，不能作为严格双写契约的参考。mini-code-agent 第一版若需要明确失败语义，不应照搬此处的异常吞掉行为。

## 4. History schema 与恢复能力

`history` 字段为：

```text
id (随机 UUID，主键)
memory_id
old_memory
new_memory
event
created_at
updated_at
is_deleted
actor_id
role
```

每次 `add_history` 自己生成新的随机 event ID，并在一条独立 SQLite transaction 中提交；失败只回滚这条 SQLite transaction。[本地 `add_history`](/Users/ywq/learn/mem0/mem0/memory/storage.py:150)，[官方 `add_history`](https://github.com/mem0ai/mem0/blob/4debc58a83377b18be81ae1e5969a300736b2fac/mem0/memory/storage.py#L138-L179)

`get_history` 按 `created_at ASC, DATETIME(updated_at) ASC` 排序，没有显式 sequence/version。[本地 `get_history`](/Users/ywq/learn/mem0/mem0/memory/storage.py:227)，[官方 `get_history`](https://github.com/mem0ai/mem0/blob/4debc58a83377b18be81ae1e5969a300736b2fac/mem0/memory/storage.py#L213-L240)

它足以展示正常路径下的文本变化历史，但不能单独、可靠地重建完整 vector store：

- 没有 `user_id`、`agent_id`、`run_id` 等 scope；
- 没有任意 payload metadata；
- 没有 embedding/BM25 模型与 collection 配置；
- 没有 dense/sparse vector（理论上可重新编码，但需要外部提供正确配置）；
- 没有 per-memory version 或强序列号；
- 双写窗口及批量异常吞掉可能使事件缺失，或者出现没有对应 Point 的 ADD event。

因此准确评价是：Mem0 的 SQLite 表是 history/audit 记录，不是完整的灾难恢复日志。可以从它推导部分文本生命周期，但官方代码没有提供从 history 重建 vector store 的流程或完整数据保证。

## 5. 并发、锁、version 与幂等性

- `SQLiteManager` 有一个实例级 `threading.Lock`，只包住每次 SQLite 方法及其本地 transaction；它不会覆盖 `vector_store → history` 整段操作，也不协调另一个进程或另一个 `SQLiteManager` 实例。[本地锁](/Users/ywq/learn/mem0/mem0/memory/storage.py:11)
- `Memory` / `AsyncMemory` 没有 per-memory 锁、全局写锁或分布式锁。
- UPDATE 是无 version 的 read-modify-write；没有 optimistic compare-and-swap。并发更新可能 last-write-wins，而两条 history 可能都把相同旧值记录为 `old_memory`。
- schema 没有 per-memory `version`、唯一操作键或 event sequence。
- `add_history` 的 event ID 在函数内部随机生成，调用者不能用固定 event ID 幂等重试；重试可能多写一条事件。
- Qdrant adapter 对指定 Point ID 使用 `upsert`，所以单次底层覆盖可以复用同一 ID；但高层 ADD 每次生成新 ID，整个 `Memory.add()` 不是幂等的。[本地 Qdrant upsert](/Users/ywq/learn/mem0/mem0/vector_stores/qdrant.py:234)

## 对 mini-code-agent 方案的直接参考

可以借鉴 Mem0 的部分：

- Qdrant Point 作为当前 Memory；
- payload `data` 保存源文本；
- vector 先成功，再记录最终成功事件；
- history 不保存可重新生成的 vector。

不应误认为 Mem0 已解决的问题：

- 它没有 Qdrant + history 的原子一致性；
- 它没有 history retry、补偿或部分成功异常；
- 它没有并发更新控制、version 或幂等操作 ID；
- 它的 history schema 不能完整恢复带 scope/metadata 的 Point；
- `infer=True` 批量 ADD 的成功语义尤其宽松。

## 明确的不确定性

1. 此分析只覆盖开源 Python SDK；Mem0 Hosted Platform 的后端实现不在该仓库中，不能据此推断 Hosted 的事务与恢复机制。
2. 各 vector-store provider 对 `insert/update/delete` 的底层原子性不同；这里只能确认 Memory 层没有跨存储事务。
3. 官方源码没有把 vector store 明文命名为 “source of truth”；这是由所有当前读取和修改都以 vector store 为准、SQLite 仅供 `history()` 使用而推导出的结论。
