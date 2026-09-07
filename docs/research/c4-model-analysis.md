# Mini Code Agent 仓库的 C4 Model 分层研究

研究日期：2026-08-23  
代码基线：当前 working tree；`HEAD` 为 `6c722f854534087da4823c59720704e704006208`  
研究范围：只讨论 Software System、Container、Component、Code 的静态层级和运行边界；不追踪一次请求的业务执行顺序。报告沿用仓库现有的 `docs/research/` 研究笔记约定。

## 0. 本文采用的 C4 判断标准

C4 是从高到低逐级放大的抽象：Software System 由一个或多个 Container 组成，Container 内有 Component，Component 再由 Code elements 实现。本文使用 C4 官方定义，而不是用本仓库的目录名或类名反推层级。

| 层级 | 本文采用的判断问题 | 官方依据 |
| --- | --- | --- |
| Software System | 它是否作为一个整体向人或其他系统提供可辨认的价值？团队是否拥有并能看到其内部实现？ | [C4 Software System](https://c4model.com/abstractions/software-system) |
| Container | 它是否是一个需要执行的应用或一个数据存储边界？它能否与其他边界通过 HTTP、数据库协议、文件或进程机制通信？ | [C4 Container](https://c4model.com/abstractions/container)、[Container diagram](https://c4model.com/diagrams/container) |
| Component | 它是否是在同一个 Container 内，把相关功能组织在清晰接口之后的一组代码？它本身是否不可独立部署，并与同 Container 的其他 Component 共享进程空间？ | [C4 Component](https://c4model.com/abstractions/component) |
| Code | 它是否是编程语言直接提供的构造，例如 class、interface/Protocol、function、module 或数据库表？ | [C4 Code](https://c4model.com/abstractions/code)、[Code diagram](https://c4model.com/diagrams/code) |

两个重要后果：

1. C4 Container 是逻辑运行或数据边界，不等于 Docker 容器，也不严格等于一个 OS process。嵌入式数据库仍可以是 data-store Container；同一个 Web 应用在不同部署中也可能使用一个或多个进程。
2. package、module、目录、类库和 class 通常只是代码组织方式。官方明确提醒，不应把 JAR、module、package、namespace 或文件夹自动当作 Component 或 Container。[C4 Container FAQ](https://c4model.com/abstractions/container)；[C4 Component FAQ](https://c4model.com/abstractions/component)

## 1. Software System：推荐 scope 与备选 scope

### 1.1 推荐结论：这个仓库承载两个可区分的 Software System

#### Software System A：Mini Code Agent（交互式产品）

这是一个完整的 Software System，而不只是某个更大系统中的普通子模块。它对可信本地 User 提供一项可独立使用的软件能力：通过 Web 或 CLI 在指定工作区使用 coding agent，并持久保存 Conversation，同时维护可跨 Turn/Conversation 使用的 Memory。README 把项目作为具名产品介绍，并给出从安装、迁移到 Web/CLI 启动的完整运行方式；它不是只有一组供其他项目链接的 library。[README.md:7-15](../../README.md#L7-L15)；[README.md:39-45](../../README.md#L39-L45)；[README.md:105-132](../../README.md#L105-L132)

判断依据：

- **有整体用户价值**：用户能在本地工作区中进行有状态 coding-agent 交互，而不需要另一个本仓库内的上层应用来赋予它意义。
- **有完整运行边界**：仓库提供 Web server、CLI、Conversation 数据库、Memory data store 配置和外部模型调用配置。
- **有自己的持久状态与生命周期**：SQLite 保存 Conversation/Transcript，Qdrant 保存 Memory；Web 和 CLI 可分别启动、停止并跨进程恢复状态。[settings.py:73-81](../../config/config/settings.py#L73-L81)；[models.py:7-47](../../config/chat/models.py#L7-L47)；[ADR-0001](../../docs/adr/0001-qdrant-as-current-memory-source.md)
- **没有“只是上游系统一个子服务”的仓库证据**：仓库没有服务发现、消息队列、上层产品部署清单或仅供另一宿主调用的唯一入口。相反，它直接提供人可使用的 Web 和 CLI。依赖 Anthropic、Qdrant 或本地工作区只是与外部系统/数据边界协作，不会自动把它降为那些系统的 Component。

#### Software System B：LongMemEval Retrieval Evaluation（支持型评测系统）

推荐把正式 LongMemEval 检索评测视为另一个支持型 Software System，而不是交互式产品的一个运行中 Container。它向维护者提供“可复现地测量本项目检索质量”的独立价值；它有自己的启动命令、固定 CUDA 主机约束、数据集、模型 cache、阶段 cache、运行产物和恢复边界。文档还明确说明该 batch run 不读写产品的持久化 Memory，并把候选生成与重排拆成两个进程。[memory-and-evaluation.md:45-76](../../docs/memory-and-evaluation.md#L45-L76)；[memory-and-evaluation.md:161-178](../../docs/memory-and-evaluation.md#L161-L178)

把它独立出来的关键不是 `evals/` 目录名，而是这些运行事实：

- Web/CLI 不需要评测进程才能工作；评测也不需要 Web/CLI server。
- 评测不访问产品 SQLite Conversation 或产品 Qdrant Memory；正式阶段通过文件 artifact 连接。
- 它面向不同使用者目标：产品提供交互能力，评测提供质量证据。

### 1.2 另一种合理 scope：一个仓库级 Software System

如果讨论对象不是“用户使用的产品”，而是“团队在这个仓库中共同拥有和交付的全部 Mini Code Agent 工程能力”，也可以画成一个更宽的 Software System，把评测执行程序都作为其中的 Container。这与 C4 所说“系统边界往往接近单一团队/源码库边界”相容，但它把两种明显不同的价值和生命周期塞进一个边界，解释力较弱。[C4 Software System](https://c4model.com/abstractions/software-system)

本文后续采用“**两个 Software System**”作为主模型，同时在 Container 清单中完整覆盖仓库的主要运行边界。

### 1.3 是否是更大 Software System 的一部分？

从当前仓库本身不能得出这一结论。它当然运行在更大的“开发者工作站/AI 服务生态”中，也依赖外部模型服务和用户工作区；但 C4 的 Software System 边界按价值和所有权划分，而不是按依赖数量划分。若未来某组织把 Mini Code Agent 嵌入更大的开发平台，它可以在那个更高层 System Landscape 中表现为一个外部 Software System 或子系统；当前代码没有证明那个更大边界已经存在。

## 2. 主要 Container

### 2.1 Software System A：Mini Code Agent

#### Container A1：Browser Chat Client

1. **名称**：Browser Chat Client
2. **类型**：Client-side Web Application
3. **启动方式**：先运行 Web server，浏览器访问 `http://127.0.0.1:8000/`；HTML 加载 `chat.js` 后，该代码在浏览器进程空间执行。仓库没有单独的 frontend build/start 命令。[README.md:126-133](../../README.md#L126-L133)；[index.html:1-10](../../config/chat/templates/chat/index.html#L1-L10)
4. **为什么是 Container**：发送消息这一核心浏览器行为由 JavaScript 捕获表单、构造 JSON、发起 `fetch` 并更新 DOM；它与 Python server 不在同一进程空间，通过 HTTP/JSON 通信。关闭浏览器 tab 不会停止 server，停止 server 也不会结束已经打开的浏览器进程。[chat.js:1-44](../../config/chat/static/chat/chat.js#L1-L44)
5. **与其他 Container 的通信**：通过 HTTP 获取 HTML/CSS/JS，通过带 CSRF header 的 HTTP `POST /api/chat/` 发送 JSON，只与 Django Web Container 直接通信；不直接访问 SQLite 或 Qdrant。[chat.js:19-31](../../config/chat/static/chat/chat.js#L19-L31)；[urls.py:7-11](../../config/chat/urls.py#L7-L11)
6. **歧义**：这只有 77 行、无独立构建产物的原生 JavaScript，初始页面和 Conversation 列表由 server 渲染。C4 官方建议：以 server-rendered HTML 为主时可画成一个 Container；JavaScript 足以形成 client app 时画成两个。[官方 Web applications FAQ](https://c4model.com/abstractions/container) 本文把它单列，是因为关键聊天交互确实跨了浏览器/Python 两个 runtime boundary；若图的受众只需要粗粒度部署视图，把它并回 Web Container 也合理。

#### Container A2：Django Web Server

1. **名称**：Django Web Server
2. **类型**：Server-side Web Application / JSON API Server
3. **启动方式**：初始化 schema 用 `uv run --locked python config/manage.py migrate`；实际启动是 `uv run --locked python config/manage.py runserver`。`config.wsgi.application` 和 `config.asgi.application` 是同一逻辑 Web Container 的替代托管入口，不是两个 Container。[README.md:126-131](../../README.md#L126-L131)；[manage.py:8-23](../../config/manage.py#L8-L23)；[wsgi.py:10-16](../../config/config/wsgi.py#L10-L16)；[asgi.py:10-16](../../config/config/asgi.py#L10-L16)
4. **为什么是 Container**：它是可单独启动/停止的 HTTP server，拥有 Django URL、view、template rendering、核心执行代码和进程内资源。它不是因为文件名中有 `server` 才成立，而是因为 `runserver`/WSGI/ASGI 会建立长期 HTTP runtime boundary。
5. **与其他 Container 的通信**：与 Browser Chat Client 通过 HTTP/HTML/JSON；通过 Django ORM/SQLite driver 访问 Conversation SQLite Database；通过 Qdrant client 的本地嵌入式调用或 HTTP URL 访问 Memory Store；通过 Anthropic SDK 的 HTTP(S) 调用外部模型系统；通过本地文件 I/O 和短命子进程访问用户工作区。[views.py:140-176](../../config/chat/views.py#L140-L176)；[settings.py:43-81](../../config/config/settings.py#L43-L81)；[composition.py:81-108](../../config/chat/composition.py#L81-L108)；[agent_runtime.py:251-278](../../config/core/agent_runtime.py#L251-L278)
6. **具体边界证据**：根 URL config 把请求交给 `chat.urls`，后者暴露页面、新建 Conversation 和 JSON chat 三个 HTTP route。[config/urls.py:18-24](../../config/config/urls.py#L18-L24)；[chat/urls.py:1-11](../../config/chat/urls.py#L1-L11)

#### Container A3：Interactive CLI

1. **名称**：Mini Code Agent CLI
2. **类型**：Console Application / CLI
3. **启动方式**：`uv run --locked python config/cli.py`，另有 `--list` 和 `--resume <uuid>` 模式。[README.md:133-139](../../README.md#L133-L139)；[cli.py:74-103](../../config/cli.py#L74-L103)
4. **为什么是 Container**：`cli.py` 有自己的 `main()`、终端输入循环和进程生命周期；Web server 停止时 CLI 仍能运行。它不是 Web 的一个 HTTP client：它执行 `django.setup()` 后直接加载同一批 Python 模块。[cli.py:74-90](../../config/cli.py#L74-L90)；[cli.py:125-152](../../config/cli.py#L125-L152)
5. **与其他 Container 的通信**：它不通过 HTTP 调用 Django Web Server，也不与 Browser Chat Client 通信；它通过 Django ORM/SQLite driver 访问同一个 Conversation database，通过 Qdrant client 访问 Memory Store，通过 HTTP(S) 调用外部模型系统，并直接访问当前工作区文件系统。
6. **具体边界证据**：CLI 在自己的进程中导入 `run_conversation_turn` 和 `build_cli_runner`，以普通 Python 函数/方法调用复用代码；这正说明“共享源码”不等于“同一个 Container”。[cli.py:81-90](../../config/cli.py#L81-L90)；[cli.py:137-148](../../config/cli.py#L137-L148)

#### Container A4：Conversation SQLite Database

1. **名称**：Conversation SQLite Database
2. **类型**：Relational Database / Data Store
3. **启动方式**：没有独立 daemon；`manage.py migrate` 创建/升级 `config/db.sqlite3` schema，Web 或 CLI 进程通过 SQLite driver 打开该文件。[settings.py:73-81](../../config/config/settings.py#L73-L81)
4. **为什么是 Container**：C4 明确把 database/schema 视为 Container。SQLite 虽嵌入调用进程，但数据拥有独立、跨进程存续的 schema 和生命周期；Web 或 CLI 退出后 Conversation、Memory Space 和 ConversationMessage 仍存在。[C4 Container](https://c4model.com/abstractions/container)；[models.py:7-47](../../config/chat/models.py#L7-L47)
5. **与其他 Container 的通信**：Django Web Server 和 CLI 都通过 Django ORM 形成的 SQLite database connection/file I/O 读写它；Browser 不直接连接；评测程序不使用它。
6. **具体边界证据**：三个项目模型以及外键/排序约束定义在 `chat/models.py`，Django migrations 物化 schema。[0001_initial.py:17-69](../../config/chat/migrations/0001_initial.py#L17-L69)；[0002_conversationmessage.py:12-39](../../config/chat/migrations/0002_conversationmessage.py#L12-L39)

#### Container A5：Qdrant Memory Store

1. **名称**：Qdrant Memory Store（逻辑上是本系统拥有的 collection/data store）
2. **类型**：Vector/Document Data Store
3. **启动方式**：默认 `MEMORY_QDRANT_LOCATION=~/.mini-code-agent/qdrant`，由应用第一次构造 Memory 时以 `QdrantClient(path=...)` 嵌入式打开；也可设为 `:memory:`，或设为 `http(s)://...` 连接预先启动的 Qdrant service。仓库没有提供启动远程 Qdrant service 的脚本。[.env.example:4-7](../../.env.example#L4-L7)；[memory/composition.py:39-44](../../config/core/memory/composition.py#L39-L44)
4. **为什么是 Container**：它是 Memory 当前状态的权威 data store，拥有 collection、vector config、payload 和跨调用生命周期。默认部署没有独立 daemon 不会取消其 C4 data-store 身份；在 service URL 部署中，其独立启动/停止和 HTTP 边界更明显。[ADR-0001](../../docs/adr/0001-qdrant-as-current-memory-source.md)；[qdrant_store.py:55-76](../../config/core/memory/qdrant_store.py#L55-L76)；[qdrant_store.py:185-203](../../config/core/memory/qdrant_store.py#L185-L203)
5. **与其他 Container 的通信**：Web 和 CLI 进程中的 Qdrant client 读写同一逻辑 collection；本地模式是进程内 client 加本地 data files，URL 模式是 HTTP client/server。项目文档明确要求 Web 与 CLI 并发时改用共享 service URL。[usage.md:127-141](../../docs/usage.md#L127-L141)
6. **歧义**：可以把远程 Qdrant service 画成外部 Software System，再把本项目拥有的 collection 画成本系统 Container；也可直接把该 store 作为本系统的 Container。C4 官方对托管数据服务的建议是：只要团队拥有并负责 bucket/schema，它仍可作为系统内 Container。[C4 data storage FAQ](https://c4model.com/abstractions/container)

### 2.2 Software System B：LongMemEval Retrieval Evaluation

#### Container B1：Local Retrieval Evaluation CLI

1. **名称**：Local Retrieval Evaluation CLI
2. **类型**：Batch/Console Application
3. **启动方式**：`uv run --locked python config/evals/memory_retrieval/run.py ...`；可运行内置 cases 或传入 LongMemEval dataset，并比较多个 reranker。[memory-and-evaluation.md:142-159](../../docs/memory-and-evaluation.md#L142-L159)；[run.py:70-99](../../config/evals/memory_retrieval/run.py#L70-L99)
4. **为什么是 Container**：它有自己的 `main()` 和一次性 batch 生命周期，Web/CLI 不会加载或管理这个进程。[run.py:315-383](../../config/evals/memory_retrieval/run.py#L315-L383)
5. **通信**：读取 JSON dataset/cases，使用进程内 `QdrantClient(":memory:")` 作为临时索引，并向 stdout 输出报告；不访问产品 SQLite 或产品 Qdrant。[run.py:102-147](../../config/evals/memory_retrieval/run.py#L102-L147)
6. **备注**：它是便于普通开发机运行的评测入口，不是正式 CUDA baseline runner。

#### Container B2：CUDA Evaluation Orchestrator

1. **名称**：CUDA Evaluation Orchestrator
2. **类型**：Shell/Batch Application
3. **启动方式**：设置 `MINI_CODE_AGENT_RUN_ID` 后运行 `./scripts/run_longmemeval_cu124.sh`。[memory-and-evaluation.md:161-170](../../docs/memory-and-evaluation.md#L161-L170)
4. **为什么是 Container**：C4 官方明确把 shell script 列为可能的 Container；该 290 行脚本拥有运行锁、环境准备、主机预检、模型/数据准备、阶段调度和自己的 batch 生命周期，而不只是一个命令别名。[C4 Container](https://c4model.com/abstractions/container)；[run_longmemeval_cu124.sh:120-190](../../scripts/run_longmemeval_cu124.sh#L120-L190)
5. **通信**：通过 OS process invocation 启动 dataset downloader、Candidate process 和 Reranking process；通过退出码、stdout/stderr pipe 和 Evaluation Artifact Store 协调它们。[run_longmemeval_cu124.sh:227-286](../../scripts/run_longmemeval_cu124.sh#L227-L286)
6. **具体部署证据**：它直接运行在固定 Linux CUDA host 的 uv-managed Python environment；ADR 明确排除 Docker，并固定硬件/驱动/Python/CUDA profile。[ADR-0009](../../docs/adr/0009-pin-retrieval-evaluation-to-one-cuda-host.md)；[ADR-0010](../../docs/adr/0010-use-native-uv-for-cuda-retrieval-evaluation.md)

#### Container B3：Candidate Retrieval Batch Process

1. **名称**：Candidate Retrieval Batch Process
2. **类型**：GPU Batch Application
3. **启动方式**：orchestrator 用 `python -m evals.memory_retrieval.run_longmemeval_cuda candidates ...` 分别启动 smoke/full；该 subcommand 也可直接启动。[run_longmemeval_cu124.sh:254-265](../../scripts/run_longmemeval_cu124.sh#L254-L265)；[run_longmemeval_cuda.py:62-83](../../config/evals/memory_retrieval/run_longmemeval_cuda.py#L62-L83)
4. **为什么是 Container**：它是独立 Python process，独占加载 E5/BM25 相关资源，完成后释放 GPU/进程资源；它与下一阶段不是普通函数调用连接。
5. **通信**：读取固定 dataset/model snapshots，把 candidate JSONL、manifest 和 metrics 写入 Evaluation Artifact Store；内部每题的 `QdrantClient(":memory:")` 是临时进程内实现，不是跨进程 Container。[candidate_stage.py:394-425](../../config/evals/memory_retrieval/candidate_stage.py#L394-L425)；[candidate_stage.py:505-566](../../config/evals/memory_retrieval/candidate_stage.py#L505-L566)
6. **具体边界证据**：正式文档要求候选阶段完成并释放 E5 后，才由第二个进程加载 BGE。[memory-and-evaluation.md:64-76](../../docs/memory-and-evaluation.md#L64-L76)

#### Container B4：BGE Reranking Batch Process

1. **名称**：BGE Reranking Batch Process
2. **类型**：GPU Batch Application
3. **启动方式**：orchestrator 用一个 fresh process 执行 `python -m evals.memory_retrieval.run_longmemeval_cuda rerank ...`。[run_longmemeval_cu124.sh:267-286](../../scripts/run_longmemeval_cu124.sh#L267-L286)；[run_longmemeval_cuda.py:84-95](../../config/evals/memory_retrieval/run_longmemeval_cuda.py#L84-L95)
4. **为什么是 Container**：它与 candidate stage 有不同 process lifetime、模型驻留和输入边界；脚本刻意让二者不同时驻留在 8 GiB GPU 上。[ADR-0013](../../docs/adr/0013-separate-candidate-retrieval-from-bge-reranking.md)
5. **通信**：从 Evaluation Artifact Store 读取 candidate manifest/JSONL，写入 reranked JSONL、manifest 和 baseline JSON；与 Candidate process 之间没有 HTTP/RPC，也没有 Python 内存对象共享。[run_longmemeval_cuda.py:260-289](../../config/evals/memory_retrieval/run_longmemeval_cuda.py#L260-L289)；[rerank_stage.py:193-229](../../config/evals/memory_retrieval/rerank_stage.py#L193-L229)
6. **具体边界证据**：`run_rerank_stage` 先加载已经完成的 candidate artifact，并检查数据集/问题顺序，再建立自己的 cache 和 run artifact。[rerank_stage.py:205-229](../../config/evals/memory_retrieval/rerank_stage.py#L205-L229)

#### Container B5：Evaluation Artifact Store

1. **名称**：Evaluation Artifact Store
2. **类型**：File System Data Store
3. **启动方式**：没有进程；orchestrator 在 `~/.local/share/mini-code-agent/eval/`（或环境变量覆盖位置）创建 `cache/`、`runs/`、dataset 和 model directories。[run_longmemeval_cu124.sh:8-18](../../scripts/run_longmemeval_cu124.sh#L8-L18)；[run_longmemeval_cu124.sh:131-141](../../scripts/run_longmemeval_cu124.sh#L131-L141)
4. **为什么是 Container**：C4 把文件系统或其一部分列为 data-store Container。这里的 candidate JSONL 和 completed-case ledger 是官方项目决策指定的持久 cache/resume boundary；进程结束后状态仍存在，并在下次 process 启动时复用。[C4 Container](https://c4model.com/abstractions/container)；[ADR-0013](../../docs/adr/0013-separate-candidate-retrieval-from-bge-reranking.md)
5. **通信**：orchestrator、Candidate process、Reranking process 和 downloader 通过普通文件 I/O 共享 dataset、model cache、manifests、JSONL、logs 与 baseline；写 JSON 使用临时文件后 rename 的原子替换。[artifact_io.py:34-65](../../config/evals/memory_retrieval/artifact_io.py#L34-L65)
6. **具体边界证据**：文档列出了 `runs/<RUN_ID>/` 中的 baseline、两个 stage manifest、环境清单和 logs。[memory-and-evaluation.md:174-190](../../docs/memory-and-evaluation.md#L174-L190)

### 2.3 独立入口不一定都是“主要 Container”

以下内容确实可执行，但没有必要在主 Container 图中各画一个框：

- `config/manage.py migrate` 是数据库 schema 管理操作；`runserver`、WSGI、ASGI 才是同一 Web Container 的运行入口变体，不应把每个 management command 画成 Container。
- `download_longmemeval.py` 是有 `main()` 的一次性下载 helper，正式 orchestrator 会把它作为子进程调用。只有当数据供应本身成为需要独立运维/监控的能力时，才值得把它提升为单独 Container。[download_longmemeval.py:41-110](../../config/evals/memory_retrieval/download_longmemeval.py#L41-L110)
- tests、Ruff、mypy、coverage 和 GitHub Actions job 是开发/验证执行，不是产品或评测系统持续提供价值所需的运行单元。[ci.yml:15-50](../../.github/workflows/ci.yml#L15-L50)
- `AgentRuntime` 虽然名字中有 Runtime，却由 Web/CLI 各自在本进程中普通构造，并通过 `runner.run(...)` 直接调用；没有监听端口、queue consumer 或独立启动入口。因此它是 Component 中的重要 Code，而不是 Container。[composition.py:81-108](../../config/chat/composition.py#L81-L108)；[application.py:248-268](../../config/chat/application.py#L248-L268)
- `Memory`、`QdrantStore`、各种 `*Manager` class 同理：类名不提供 C4 runtime boundary。需要单列的是它们连接的 Qdrant data store，而不是 Python class 自身。
- agent 执行工具时产生的 shell child process 是短命的实现活动，不是稳定、可独立部署和运维的系统运行单元，因此不在主图中把“每条 bash 命令”画成 Container。[tooling.py:27-51](../../config/core/tooling.py#L27-L51)

### 2.4 外部元素，不是本仓库 Software System 内的 Container

- **Anthropic Messages API 或 `ANTHROPIC_BASE_URL` 指向的兼容服务**：外部 Software System；Web/CLI 中的 Python client 通过 HTTP(S) 使用它，本仓库不拥有或启动服务端。[composition.py:26-31](../../config/chat/composition.py#L26-L31)；[agent_runtime.py:333-347](../../config/core/agent_runtime.py#L333-L347)
- **用户选择的 Workspace**：可以在更宽的 C4 图中画成外部 File System/Data Store。它是被操作的用户资源，不是该仓库部署出来的数据存储；工具代码通过本地文件 I/O和子进程使用它。[tooling.py:12-24](../../config/core/tooling.py#L12-L24)；[tooling.py:40-47](../../config/core/tooling.py#L40-L47)
- **Hugging Face dataset/model hosting**：评测系统使用的外部内容服务；下载器通过 HTTPS 获取固定 revision 的 dataset。[download_longmemeval.py:9-16](../../config/evals/memory_retrieval/download_longmemeval.py#L9-L16)；[download_longmemeval.py:53-69](../../config/evals/memory_retrieval/download_longmemeval.py#L53-L69)

## 3. 核心 Container 的 Component：Django Web Server

这里选择 Django Web Server，因为它是 README 推荐的人类入口，也是拥有最多服务器端职责的主要 Container。下面所有 Component 都作为 Python 模块被同一个 Django server process 加载，并通过普通函数、方法、Protocol 或 Django ORM API 交互；它们没有各自的启动命令、监听端口或独立部署生命周期。

同一批共享 Python 代码也会被 CLI 进程加载。这不表示 Web 与 CLI 是同一 Container，而表示源码被嵌入两个不同运行边界；本节只描述它们位于 **Django Web Server 实例中** 时的 Component 归属。

### Component A2.1：HTTP Presentation

1. **职责**：定义 server-side route，验证 HTTP 输入，渲染页面/Transcript 投影，产生 redirect 或 JSON response。
2. **主要代码**：`config/config/urls.py`、`config/chat/urls.py`、`config/chat/views.py`、server-side template `config/chat/templates/chat/index.html`。[views.py:25-68](../../config/chat/views.py#L25-L68)；[views.py:70-115](../../config/chat/views.py#L70-L115)
3. **与其他 Component 的接口**：对外暴露 HTTP routes；对内通过 `list_conversations`、`load_conversation_messages`、`start_conversation`、`run_conversation_turn` 等 Python functions 调用 Conversation Coordination，并把 `build_web_runner` function 作为构造依赖传入。[views.py:10-20](../../config/chat/views.py#L10-L20)
4. **为什么不是 Container**：这些 route/view/template 没有自己的 server；它们只在 Django server 已运行时执行，且不能独立停止。
5. **进程空间**：server-side 部分与下述所有 Component 同处一个 Django Python process。`chat.js` 在 Browser Container 中执行，是前述边界歧义，不属于此 server-side Component 的执行空间。

### Component A2.2：Conversation Coordination

1. **职责**：提供 Conversation 的创建、列举、恢复、工作区检查、Transcript 持久读写，以及对一次 agent 执行结果的协调边界。
2. **主要代码**：`config/chat/application.py` 中的 public functions、数据对象、错误类型与 `AgentRunner` Protocol。[application.py:18-60](../../config/chat/application.py#L18-L60)；[application.py:75-221](../../config/chat/application.py#L75-L221)
3. **与其他 Component 的接口**：HTTP Presentation 调用其 functions；它通过 Django model API 调用 Conversation Persistence；通过 `Callable[[ConversationRuntimeContext], AgentRunner]` 和 `AgentRunner.run(...)` 使用 Runtime Construction/Agent Execution。[application.py:50-56](../../config/chat/application.py#L50-L56)；[application.py:248-268](../../config/chat/application.py#L248-L268)
4. **为什么不是 Container**：没有独立进程或网络接口；`run_conversation_turn` 是导入后直接调用的 Python function。
5. **进程空间**：与调用它的 Django views 和它构造/调用的 runner 同处 Web process。

### Component A2.3：Runtime Construction and Configuration

1. **职责**：从环境变量读取模型/Qdrant配置，构造并缓存 production Memory，创建适用于 Web 的 `AgentRuntime`，并管理 Memory 关闭。
2. **主要代码**：`config/chat/composition.py` 与 `config/core/memory/composition.py`。[composition.py:26-61](../../config/chat/composition.py#L26-L61)；[memory/composition.py:23-67](../../config/core/memory/composition.py#L23-L67)
3. **与其他 Component 的接口**：向 HTTP/Conversation code 暴露 `build_web_runner(context)`；向 Agent Execution 提供构造好的 `AgentRuntime`；向 Memory Component 调用 `build_memory(...)`。[composition.py:81-116](../../config/chat/composition.py#L81-L116)
4. **为什么不是 Container**：这些是 object construction functions 和 process-local cache，没有独立 runtime boundary。
5. **进程空间**：每个 Web process 拥有自己的 cache 和 client objects；CLI 进程会另建自己的副本。

### Component A2.4：Agent Execution

1. **职责**：在固定 workspace/config 下维护一轮执行所需状态，使用 model client，组织工具结果，并返回新生成的 protocol messages。
2. **主要代码**：`config/core/agent_runtime.py` 中的 `AgentRuntime`、`AgentRuntimeConfig`、`AgentMemory`/`MessageClient` Protocol 和消息规范化 helpers。[agent_runtime.py:44-87](../../config/core/agent_runtime.py#L44-L87)；[agent_runtime.py:193-250](../../config/core/agent_runtime.py#L193-L250)
3. **与其他 Component 的接口**：实现 Conversation Coordination 期待的 `AgentRunner.run(...)` 形状；通过 `MessageClient.messages.create(...)` 调用外部模型；通过 `AgentMemory.recall/add` 使用 Memory；通过 callable handler 和 `ContextCompactor` 使用 Tooling/Context Compaction。[agent_runtime.py:320-342](../../config/core/agent_runtime.py#L320-L342)
4. **为什么不是 Container**：`AgentRuntime(...)` 是 Web process 中的普通 Python object，每次需要时构造；`run()` 是同步方法，不是 worker endpoint。
5. **进程空间**：与 Django request-handling code 同一 Python process；模型服务、数据库和远程 Qdrant 才在该进程之外。

### Component A2.5：Tooling and Workspace Services

1. **职责**：声明工具 schema，实施 shell/文件/glob 操作、workspace path 检查与权限/log/output hooks，并管理进程内 todo 和 workspace skills。
2. **主要代码**：`config/core/tooling.py`、`config/core/todo.py`、`config/core/skills.py`、`config/core/frontmatter.py`。[tooling.py:12-156](../../config/core/tooling.py#L12-L156)；[skills.py:17-105](../../config/core/skills.py#L17-L105)；[todo.py:4-55](../../config/core/todo.py#L4-L55)
3. **与其他 Component 的接口**：Agent Execution 复制 `TOOLS` schema，建立 name-to-callable handler map，并直接调用 `permission_hook`、`run_bash`、`run_read` 等 functions。[agent_runtime.py:248-278](../../config/core/agent_runtime.py#L248-L278)；[agent_runtime.py:362-409](../../config/core/agent_runtime.py#L362-L409)
4. **为什么不是 Container**：它是一组被调用的 Python functions/classes；短命 shell child process 不把整个工具模块变成可独立运维的应用。
5. **进程空间**：tool dispatch、policy、todo、skill parsing 都在 Web process；文件和 shell 命令触及的用户 Workspace 位于进程外的数据/OS边界。

### Component A2.6：Context Compaction

1. **职责**：在 model call 前保存 snapshot、限制大型 tool output、缩减历史，并在需要时调用注入的 summarization function。
2. **主要代码**：`config/core/compaction.py` 的 `CompactionConfig`、`ContextCompactor` 及其 module helpers。[compaction.py:14-61](../../config/core/compaction.py#L14-L61)；[compaction.py:125-194](../../config/core/compaction.py#L125-L194)
3. **与其他 Component 的接口**：Agent Execution 通过 `prepare_for_model(messages)` 和 `compact_history(messages)` 直接调用；Runtime Construction 把 `_summarize` callable 注入构造函数。[agent_runtime.py:243-247](../../config/core/agent_runtime.py#L243-L247)；[agent_runtime.py:333-334](../../config/core/agent_runtime.py#L333-L334)
4. **为什么不是 Container**：它没有独立执行入口，只是一个 process-local object；写入 `.transcription`/`.tool_result` 是对 Workspace 的文件 I/O。
5. **进程空间**：与 `AgentRuntime` 同一 Web process。

### Component A2.7：Memory Management

1. **职责**：以 `Memory.add/recall` 作为整体接口，组织 Memory extraction、dense/BM25 encoding、ranking/reranking，并把持久读写委托给 Qdrant client-side code。
2. **主要代码**：`config/core/memory/memory.py`、`extraction.py`、`embedder.py`、`reranker.py`、`bge_reranker.py`、`vector_store.py`、`qdrant_store.py`、`llm.py`。它被视为一个 Component 不是因为共处 `memory/` 目录，而是因为外部使用方只需面向紧凑的 `Memory.add/recall/close` 功能面。[memory.py:40-66](../../config/core/memory/memory.py#L40-L66)；[memory.py:146-231](../../config/core/memory/memory.py#L146-L231)
3. **与其他 Component 的接口**：Agent Execution 通过 `AgentMemory` 所描述的 `recall/add` 方法使用它；Runtime Construction 通过 `build_memory` 组装它；内部通过 `MemoryVectorStore` Protocol 调用 `QdrantStore`，后者再连接 Qdrant Memory Store。[vector_store.py:14-45](../../config/core/memory/vector_store.py#L14-L45)；[qdrant_store.py:81-183](../../config/core/memory/qdrant_store.py#L81-L183)
4. **为什么不是 Container**：`Memory`/`QdrantStore` 都是 Web process 中的 Python objects；真正的数据边界是 Qdrant Memory Store。若配置 URL，跨进程 HTTP 出现在 `QdrantClient` 与 store 之间，而不是 Agent Execution 与 `Memory` class 之间。
5. **进程空间**：Memory coordination、encoding 和 reranking code 与 Django Web process 相同；远程 Qdrant 和外部模型服务不在其中。默认本地 Qdrant client 也在该进程执行，但其持久 data store 仍单列为 Container。

### Component A2.8：Conversation Persistence

1. **职责**：定义 User 之外的项目关系模型和 ORM mapping：Memory Space、Conversation、ConversationMessage，以及相应 database migrations。
2. **主要代码**：`config/chat/models.py` 和 `config/chat/migrations/`。[models.py:7-47](../../config/chat/models.py#L7-L47)
3. **与其他 Component 的接口**：Conversation Coordination 使用 Django model managers、querysets、related managers 和 `transaction.atomic()`；该 Component 通过 Django database backend 连接 Conversation SQLite Database。[application.py:63-87](../../config/chat/application.py#L63-L87)；[application.py:112-165](../../config/chat/application.py#L112-L165)
4. **为什么不是 Container**：Django model classes 是 database mapping Code，不是数据库本身，也没有独立进程。SQLite schema/file 才是 data-store Container。
5. **进程空间**：ORM mapping 和 query construction 在 Web process；SQLite data boundary 独立存在。

### 3.1 Component 划分的合理歧义

C4 的 Component 并非 Python 可自动识别的语法单位，因此以下调整也合理：

- 小图可把 Runtime Construction 合并进 Conversation Coordination，因为前者代码较少且只提供 factory/resource lifecycle。
- 更细的图可把 Memory Management 拆为 extraction、retrieval/ranking 和 Qdrant client-side storage 三个 Component；当前报告保留一个组件，是因为 `Memory` 对外形成统一的小接口，并且用户只要求主要 Component。
- 不应把 `config/chat/` 整个目录画成一个 Component：它同时包含 HTTP、协调、构造和持久化等多种责任。
- 也不应把 `config/core/` 整个目录画成一个 Component：Agent Execution、Tooling、Context Compaction 和 Memory 有不同职责与接口。
- 不应按每个 `*Service`、`*Manager` 或 module 各画一个 Component；代码元素数量并不是组件数量。

## 4. 代表性的 Code level 例子

下表从每个主要 Component 选出 1–3 个 Code elements。它们是 Component 的实现材料，而不是 Component 本身；即使某个 class 很重要或名字中含 `Runtime`/`Store`，单个语言构造也不会因此获得独立 runtime boundary。

| Component | Code element | 为什么是 Code，而不是 Component |
| --- | --- | --- |
| HTTP Presentation | `index()` ([views.py:70](../../config/chat/views.py#L70)) | 一个 Django view function；实现页面 route 的一部分。 |
| HTTP Presentation | `new_conversation()` ([views.py:118](../../config/chat/views.py#L118)) | 一个处理 POST/redirect 的 function；与其他 view/template code 合起来才形成该职责组。 |
| HTTP Presentation | `chat_api()` ([views.py:140](../../config/chat/views.py#L140)) | 一个 JSON endpoint function；它没有独立 server/process。 |
| Conversation Coordination | `AgentRunner` ([application.py:50](../../config/chat/application.py#L50)) | Python `Protocol`，只描述 `run` 方法形状。 |
| Conversation Coordination | `ConversationRuntimeContext` ([application.py:36](../../config/chat/application.py#L36)) | 一个 immutable dataclass 数据结构。 |
| Conversation Coordination | `run_conversation_turn()` ([application.py:248](../../config/chat/application.py#L248)) | 一个协调 function，是 Component 暴露的一个调用点而非运行单元。 |
| Runtime Construction and Configuration | `_production_memory()` ([composition.py:44](../../config/chat/composition.py#L44)) | 一个带 process-local `lru_cache` 的 factory function。 |
| Runtime Construction and Configuration | `_build_runner()` ([composition.py:81](../../config/chat/composition.py#L81)) | 一个 object construction function。 |
| Runtime Construction and Configuration | `build_web_runner()` ([composition.py:111](../../config/chat/composition.py#L111)) | 一个薄 public factory function，不监听网络也不能独立启动。 |
| Agent Execution | `AgentRuntimeConfig` ([agent_runtime.py:68](../../config/core/agent_runtime.py#L68)) | 一个 configuration dataclass。 |
| Agent Execution | `MessageClient` ([agent_runtime.py:63](../../config/core/agent_runtime.py#L63)) | 一个 Python `Protocol`，用于约束 client object 的形状。 |
| Agent Execution | `AgentRuntime` ([agent_runtime.py:213](../../config/core/agent_runtime.py#L213)) | 一个重要 class，但仍由 Web/CLI 进程实例化；class 是 Code level。 |
| Tooling and Workspace Services | `safe_path()` ([tooling.py:12](../../config/core/tooling.py#L12)) | 一个 path validation function。 |
| Tooling and Workspace Services | `run_bash()` ([tooling.py:27](../../config/core/tooling.py#L27)) | 一个 subprocess wrapper function；被 handler map 调用。 |
| Tooling and Workspace Services | `permission_hook()` ([tooling.py:262](../../config/core/tooling.py#L262)) | 一个 policy function，而非独立权限服务。 |
| Context Compaction | `CompactionConfig` ([compaction.py:14](../../config/core/compaction.py#L14)) | 一个参数 dataclass。 |
| Context Compaction | `ContextCompactor` ([compaction.py:32](../../config/core/compaction.py#L32)) | 一个封装 compaction 行为的 class；它的实例属于 `AgentRuntime`。 |
| Context Compaction | `prepare_for_model()` ([compaction.py:48](../../config/core/compaction.py#L48)) | class 上的一个 method。 |
| Memory Management | `Memory` ([memory.py:40](../../config/core/memory/memory.py#L40)) | Component 对外的主要 facade class，但它本身仍是 Code。 |
| Memory Management | `MemoryVectorStore` ([vector_store.py:14](../../config/core/memory/vector_store.py#L14)) | 一个 Python `Protocol`，描述持久读写所需的方法集合。 |
| Memory Management | `QdrantStore` ([qdrant_store.py:55](../../config/core/memory/qdrant_store.py#L55)) | 一个 client-side implementation class；不能与 Qdrant data-store Container 混同。 |
| Conversation Persistence | `MemorySpace` ([models.py:7](../../config/chat/models.py#L7)) | 一个 Django model class/schema mapping。 |
| Conversation Persistence | `Conversation` ([models.py:25](../../config/chat/models.py#L25)) | 一个 Django model class；对应数据库记录结构，不是 database Container。 |
| Conversation Persistence | `ConversationMessage` ([models.py:37](../../config/chat/models.py#L37)) | 一个 Django model class；与其他 model/migration code 一起形成持久化 Component。 |

## 5. 最终树

推荐树先把 **Repository** 标为普通代码管理边界，而不是 C4 element；其下有两个 Software System。只对最核心的 Django Web Server 展开 Component 和代表性 Code。

```text
Repository: mini-code-agent                         [不是 C4 层级]
├── Software System A: Mini Code Agent
│   ├── Container A1: Browser Chat Client          [Client-side Web Application；有边界歧义]
│   ├── Container A2: Django Web Server            [Server-side Web Application / JSON API]
│   │   ├── Component A2.1: HTTP Presentation
│   │   │   ├── Code: index()
│   │   │   ├── Code: new_conversation()
│   │   │   └── Code: chat_api()
│   │   ├── Component A2.2: Conversation Coordination
│   │   │   ├── Code: AgentRunner Protocol
│   │   │   ├── Code: ConversationRuntimeContext
│   │   │   └── Code: run_conversation_turn()
│   │   ├── Component A2.3: Runtime Construction and Configuration
│   │   │   ├── Code: _production_memory()
│   │   │   ├── Code: _build_runner()
│   │   │   └── Code: build_web_runner()
│   │   ├── Component A2.4: Agent Execution
│   │   │   ├── Code: AgentRuntimeConfig
│   │   │   ├── Code: MessageClient Protocol
│   │   │   └── Code: AgentRuntime
│   │   ├── Component A2.5: Tooling and Workspace Services
│   │   │   ├── Code: safe_path()
│   │   │   ├── Code: run_bash()
│   │   │   └── Code: permission_hook()
│   │   ├── Component A2.6: Context Compaction
│   │   │   ├── Code: CompactionConfig
│   │   │   ├── Code: ContextCompactor
│   │   │   └── Code: prepare_for_model()
│   │   ├── Component A2.7: Memory Management
│   │   │   ├── Code: Memory
│   │   │   ├── Code: MemoryVectorStore Protocol
│   │   │   └── Code: QdrantStore
│   │   └── Component A2.8: Conversation Persistence
│   │       ├── Code: MemorySpace
│   │       ├── Code: Conversation
│   │       └── Code: ConversationMessage
│   ├── Container A3: Interactive CLI              [Console Application]
│   ├── Container A4: Conversation SQLite Database [Relational Data Store]
│   └── Container A5: Qdrant Memory Store           [Vector/Document Data Store]
└── Software System B: LongMemEval Retrieval Evaluation
    ├── Container B1: Local Retrieval Evaluation CLI [Batch/Console Application]
    ├── Container B2: CUDA Evaluation Orchestrator   [Shell/Batch Application]
    ├── Container B3: Candidate Retrieval Process    [GPU Batch Application]
    ├── Container B4: BGE Reranking Process          [GPU Batch Application]
    └── Container B5: Evaluation Artifact Store      [File System Data Store]
```

若采用宽泛的仓库级 scope，只需把 A、B 两棵树外再包一个 `Software System: Mini Code Agent Engineering System`，并把 A/B 的所有 Container 提升为它的直接 children；不要把一个 Software System 误画成另一个 Software System 的 Component。若采用保守的 server-rendered Web scope，则删去 A1，把 Browser 当 Person 使用的普通浏览器环境，HTML/JavaScript 作为 A2 交付的界面资产。

## 6. 一句话校准四个层级

- **Software System** 回答“哪一整套软件能力在给谁创造价值”；这个仓库的文件边界只是线索，不是答案。
- **Container** 回答“哪些应用或数据存储形成运行/数据边界，以及边界之间用什么机制通信”；Django、CLI、SQLite、Qdrant 和分阶段 batch process 是典型例子。
- **Component** 回答“在选定 Container 内，代码按哪些明确职责与接口分组”；所有 Component 都随该 Container 部署，并在同一 process space 中执行。
- **Code** 回答“这些职责最终由哪些 class、Protocol、function、module 或 schema element 实现”；`AgentRuntime`、`QdrantStore` 等名字再宏大也仍然首先是 Code element。
