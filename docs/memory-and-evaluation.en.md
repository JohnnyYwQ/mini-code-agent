# Memory and Retrieval Evaluation Guide

[中文](memory-and-evaluation.md) · [Back to English README](../README.en.md) · [Architecture guide](architecture.en.md)

This guide connects scoped product Memory to the LongMemEval Retrieval Baseline: how Memory is written and recalled, how the evaluation builds and scores its retrieval corpus, what the recorded formal results mean, and how to reproduce the run on the pinned CUDA host.

> **Evidence status (2026-08-21):** The `20260816-cu124-v1` metrics and hashes below are the formal-run values in the project's existing records. That run's `baseline.json`, per-question records, and logs remain on the pinned CUDA host. They have not yet been recovered into this repository or independently reverified on the current workstation. This guide does not present the recorded hashes as newly verified.

## Memory in the product

### Ownership and boundaries

The current product serves exactly one trusted local User. Each Conversation belongs to one Memory Space; in the coding use case, a Memory Space corresponds to a normalized local workspace. Application resolves the trusted User, Conversation, and Memory Space before it constructs a Memory Context. Memory consumes that context but cannot create, switch, or authorize a Memory Space.

| Concept | Visibility | Storage boundary |
| --- | --- | --- |
| User Memory | Every Memory Space owned by the same User | User ID only; no Space ID |
| Space Memory | Every Conversation in one Memory Space | Both User ID and Space ID |
| Scope | The ownership boundary an operation may access | Comes from trusted Memory Context; the model cannot choose identities |
| Conversation Transcript | Ordered protocol messages in one Conversation | Conversation history, not Memory |

A Memory is a current retrievable long-term recollection. A Conversation Transcript is the authoritative history of user, assistant, `tool_use`, and `tool_result` messages. Resuming one Conversation reloads its Transcript; it is not the same behavior as recalling Space Memory in a different Conversation. Recalled results are temporary context for the current Turn and are not written into the Transcript.

A Qdrant Point is currently the authoritative state of a Memory and retains its Source Text. Search combines the User's User Memory with the current Space Memory. If both Scopes contain exactly the same Source Text, search returns the User Memory and hides the Space copy. The current version does not yet provide the complete UPDATE, DELETE, and Memory Event history chain.

### Recall for every Turn

Before each outer-model Turn, the Agent Runtime calls Memory recall with the latest user query and trusted Memory Context:

1. Search only the current User's User Memory and the current Memory Space's Space Memory.
2. Rank with E5 dense and BM25 keyword retrieval, then combine candidates with reciprocal-rank fusion (RRF).
3. Rerank candidates with `BAAI/bge-reranker-v2-m3` by default, return at most five, and preserve each result's Scope label.
4. Supply the results as temporary system context for this Turn; the next Turn retrieves again.

Failure to resolve a trusted identity or Memory Space prevents the Turn from starting. If retrieval infrastructure fails after resolution, the Agent Runtime logs the error and continues without recalled Memory. This fallback does not add failed retrieval data to the Conversation Transcript.

### The `remember` write flow

The outer model may call a no-argument `remember` tool during the current Turn. It cannot submit a User ID, Space ID, or arbitrary text to store. The trusted handler supplies Memory Context and assembles a rolling window containing up to five completed Turns plus visible content already present in the current Turn. Tool activity is excluded.

The extraction model processes the whole window once, may return zero or more proposed Memories, and classifies each as User Memory or Space Memory. The Memory layer copies trusted identities. Ambiguous content must use the narrower Space Scope, and parsing never silently supplies a missing classification. All candidates are validated before writing, then persisted sequentially to Qdrant. The writes are not transactional across several Memories, so earlier successful writes remain if a later one fails. A `remember` failure is returned as a non-fatal tool result and the outer Turn may continue.

See the [architecture guide](architecture.en.md) for the full responsibility flow. The governing decisions are [ADR-0001](adr/0001-qdrant-as-current-memory-source.md), [ADR-0002](adr/0002-user-and-space-memory-scopes.md), [ADR-0006](adr/0006-retrieve-memory-for-each-turn.md), and [ADR-0007](adr/0007-extract-memory-from-a-five-turn-window.md).

## LongMemEval retrieval protocol

### Corpus and scored cases

The LongMemEval Retrieval Baseline is an independent batch Retrieval Evaluation Run. It neither reads nor writes persisted product Memory. It uses the pinned official cleaned LongMemEval-S dataset and follows the official retrieval experiment's session granularity, user-only indexing, eligibility rules, and `@5`/`@10` formulas.

Every question has an independent haystack corpus and a separate temporary Qdrant collection, preventing collection-wide BM25 IDF from leaking between questions. Every haystack array position remains a distinct Haystack Session Occurrence. Even when two positions share one Source Session ID, they remain separate candidates through dense retrieval, BM25, RRF, and BGE. Only the metric boundary projects occurrences back to dataset Source Session IDs for comparison with Evidence Session labels.

The 500 source cases enter the aggregates as follows:

| Category | Count | Treatment |
| --- | ---: | --- |
| Source cases | 500 | Every question in the pinned dataset |
| Abstention Cases | 30 | No Evidence Session; retain an exclusion reason but omit from positive retrieval metrics |
| No user-side target evidence | 51 | Target evidence occurs only in locations such as assistant text; not scoreable under the user-only protocol |
| Scored cases | 419 | `500 - 30 - 51`; included in aggregate Recall and NDCG |

The six scored question types are single-session-user, single-session-assistant, single-session-preference, multi-session, temporal-reasoning, and knowledge-update. The type name does not alter the user-only corpus rule. For example, a single-session-assistant case is eligible only when the target session also contains user text marked as evidence.

### Candidate Retrieval Stage

The first stage generates rankings over each question's complete independent haystack:

- E5: pinned `intfloat/multilingual-e5-base`, `passage: ` documents, `query: ` queries, mean pooling, and normalization.
- BM25: pinned `Qdrant/bm25`, with a keyword ranking independent of dense retrieval.
- RRF: fuse E5 and BM25 with rank constant 60 and materialize the top 50 candidates.

Candidate JSONL and its completed-case ledger—not temporary Qdrant collections—form the durable Evaluation Cache and resume boundary. Cache identity covers the dataset and question IDs, model revisions, top 50, RRF 60, E5 batch size 8, dependencies, `uv.lock`, and relevant source digests.

### Reranking Stage

After the candidate process completes and releases E5 resources, a second process loads BGE and reranks the fixed RRF top-50 pool in FP16 on `cuda:0`. Defaults are BGE batch size 4 and maximum input length 512. This stage cannot expand the pool, so its result reflects ordering changes over exactly the same candidates.

The formal report retains all four pipelines so gains can be attributed to a stage:

1. BM25
2. E5
3. E5 + BM25 + RRF
4. E5 + BM25 + RRF + BGE

[ADR-0013](adr/0013-separate-candidate-retrieval-from-bge-reranking.md) governs the stage boundary and [ADR-0014](adr/0014-follow-the-official-longmemeval-retrieval-protocol.md) governs the official protocol. ADR-0014 supersedes the earlier ADR-0011 design that indexed both user and assistant roles. The public primary result uses only the user-only protocol.

## Recorded formal results

### Pipeline comparison

`20260816-cu124-v1` is recorded as a `formal` / `full` Retrieval Evaluation Run aggregating 419 scored cases:

| Retrieval pipeline | RecallAll@5 | NDCG@5 | RecallAll@10 | NDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 87.35% | 89.33% | 92.12% | 90.44% |
| E5 | 90.93% | 89.92% | 95.94% | 91.20% |
| E5 + BM25 + RRF | 90.69% | 92.17% | 96.42% | 93.26% |
| E5 + BM25 + RRF + BGE | **92.60%** | **94.74%** | **97.61%** | **95.69%** |

The final pipeline leads all four primary metrics. Relative to RRF, the BGE pipeline improves them by 1.91, 2.57, 1.19, and 2.42 percentage points. Existing records also report final-pipeline RecallAny@10 of 100%, while RecallAll@10 still misses at least one Evidence Session in 10 cases: seven multi-session and three temporal-reasoning cases. Future retrieval work should prioritize multi-session coverage and temporal relationships.

> These numbers are retrieval evidence for this project's retrievers on one pinned dataset and protocol. They are not an end-to-end LongMemEval QA score, an official leaderboard result, or evidence of general Agent performance.

### Run identity and parameters

| Field | Recorded value |
| --- | --- |
| Run ID | `20260816-cu124-v1` |
| Selection / qualification | `full` / `formal` |
| Source revision | `7b1f9466f3f334bc9f6b58225397c3daee55dbd5` |
| Worktree qualification | Recorded clean when the baseline was generated; the runner labels only a clean worktree `formal` |
| Dataset | official cleaned LongMemEval-S, revision `98d7416c24c778c2fee6e6f3006e7a073259d48f`, file `longmemeval_s_cleaned.json` |
| Candidate parameters | top 50; RRF constant 60; E5 batch size 8; one corpus per question |
| BGE parameters | RRF input; batch size 4; max length 512; FP16; `cuda:0` |

| Model | Pinned revision |
| --- | --- |
| `intfloat/multilingual-e5-base` | `d128750597153bb5987e10b1c3493a34e5a4502a` |
| `Qdrant/bm25` | `e499a1f8d6bec960aab5533a0941bf914e70faf9` |
| `BAAI/bge-reranker-v2-m3` | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |

### CUDA and provider validation

The formal entry point accepts only Ubuntu 20.04 x86_64, Python 3.13, one 8 GiB NVIDIA GeForce RTX 2070 SUPER, NVIDIA driver 550.142, PyTorch 2.6.0+cu124, and CUDA 12.4. The environment comes from the same `uv.lock` through the `cuda-eval` extra; ordinary CPU development and CUDA dependency selections are declared conflicting.

Preflight requires ONNX Runtime's `CUDAExecutionProvider` and profiles a real E5 embedding to prove that compute-heavy operators execute on CUDA and none execute on CPU. The provider list may still contain the implicit CPU provider used for shape and control nodes; that is not a silent whole-model fallback. BGE must execute in FP16 on `cuda:0`, with parameter devices recorded. See [ADR-0009](adr/0009-pin-retrieval-evaluation-to-one-cuda-host.md), [ADR-0010](adr/0010-use-native-uv-for-cuda-retrieval-evaluation.md), and [ADR-0012](adr/0012-require-cuda-for-dense-encoding-and-reranking.md).

### Hashes and evidence availability

| Item | Current record | Current status |
| --- | --- | --- |
| Dataset SHA-256 | `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442` | Enforced by the downloader; this documentation work checked the pinned code value but did not redownload the dataset |
| `full/baseline.json` SHA-256 | `e267d5696e37a0c006d354c5b21ca5bb8f2620f9a48dbdf5a881f1d6b18b9a34` | Existing project record; the file is absent locally, so the digest has not been recomputed |
| Formal baseline | Not published in the repository | Cannot be inspected from the current clone |
| Per-question JSONL and manifests | Not published in the repository | Awaiting recovery from the pinned CUDA host |
| smoke/full logs and environment list | Not published in the repository | Awaiting recovery and path/sensitivity review before publication |

The explicit integration seam for the later evidence ticket is `docs/evidence/longmemeval/20260816-cu124-v1/`. Recovered material should first enter an isolated staging location, have SHA-256 recomputed, and match the recorded baseline before compact baseline, manifests, and environment metadata are published. Large per-question records or logs that do not belong in Git should receive a stable versioned download location and digest. Until verification finishes, neither README nor this guide should turn missing files into apparent evidence links or change recorded values to match unknown artifacts.

## Reproduction workflow

### Download and local smoke

The downloader pins the dataset revision, byte size, and SHA-256. It also checks an existing file's size and digest:

```bash
uv run --locked python \
  config/evals/memory_retrieval/download_longmemeval.py
```

An ordinary development environment can run 10 scored cases to exercise the adapter and retrieval entry point. This is not the formal CUDA baseline:

```bash
uv run --locked python config/evals/memory_retrieval/run.py \
  --longmemeval config/evals/memory_retrieval/data/longmemeval_s_cleaned.json \
  --max-cases 10 \
  --reranker none \
  --reranker bge
```

### Smoke and full run on the pinned CUDA host

From the repository root on a host matching the pinned profile and with a clean checkout:

```bash
export MINI_CODE_AGENT_RUN_ID=your-run-id
./scripts/run_longmemeval_cu124.sh
```

Set `MINI_CODE_AGENT_PROXY_URL` only when downloads require a proxy. The script requires at least 40 GiB free, checks or incrementally syncs the dedicated Python 3.13 environment, validates the GPU, dependencies, dataset, and model snapshots, then runs: deterministic eight-case smoke Candidate Stage, smoke BGE Reranking Stage, 419-case full Candidate Stage, and full BGE Reranking Stage. The smoke covers six scored types, one assistant-only exclusion, and one Abstention Case.

Do not set `MINI_CODE_AGENT_ALLOW_DIRTY=1` for a formal result. That option exists for debugging and makes the generated baseline `provisional`.

### Cache, resume, and outputs

Defaults live below `~/.local/share/mini-code-agent/eval/`: `cache/candidates/` and `cache/rerank/` hold content-addressed stage caches, while `runs/<RUN_ID>/` holds this run's smoke/full manifests, baseline, environment list, and logs. The script reuses complete pinned-revision model snapshots and downloads only required files when they are incomplete.

After interruption, run the same script again with exactly the same dataset, code, lockfile, parameters, and `MINI_CODE_AGENT_RUN_ID`. Candidate and Reranking Stages read their JSONL completed-case ledgers and continue after completed questions. An identity change produces a different cache key instead of mixing incompatible records. `run.lock` prevents two CUDA runs from writing the same evaluation home concurrently.

Inspect these outputs after success:

```text
runs/<RUN_ID>/full/baseline.json
runs/<RUN_ID>/full/candidate-stage.json
runs/<RUN_ID>/full/rerank-stage.json
runs/<RUN_ID>/environment.txt
runs/<RUN_ID>/git-status.txt
runs/<RUN_ID>/full-candidates.log
runs/<RUN_ID>/full-rerank.log
```

Before publishing a Retrieval Baseline, confirm `selection=full`, `qualification=formal`, git commit and clean status, 500/30/51/419 statistics, all three model revisions, stage parameters, CUDA runtime/provider evidence, and dataset digest. Then independently compute SHA-256 for every artifact being published.

## Limitations and interpretation

- The evaluation tests retrieval ranking only; it does not run a reader LLM, generate answers, or invoke an answer judge.
- The official user-only protocol intentionally does not measure assistant-side retrieval coverage. It excludes the 51 cases without user-side evidence instead of counting them as retrieval failures.
- An Abstention Case requires system behavior that avoids answering from unsupported context. The current retrieval contract has no rejection output, so these cases do not enter positive Recall/NDCG.
- The baseline uses official data, eligibility, and formulas, but the retriever is this project's E5/BM25/RRF/BGE pipeline—not the official repository's retriever or an official leaderboard submission.
- Results apply only to the fixed dataset, code revision, model snapshots, parameters, and CUDA profile. They do not generalize to Coding Agent tasks overall.
- The missing locally published and independently reviewed formal artifacts are the most important gap in the evidence chain. Until that gap closes, call the result “recorded,” not “verified in this repository.”
