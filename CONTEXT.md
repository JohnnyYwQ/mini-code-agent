# Memory Context

This context defines the remembered facts an agent can retain, retrieve, and change while preserving ownership boundaries and an understandable change history.

## Language

**User**:
The person who owns Memory Spaces, Conversations, and Memories. In the current product scope, the application serves exactly one trusted local User.
_Avoid_: Account, Login

**Memory**:
A current, retrievable recollection retained for later agent interactions. It belongs to exactly one User, is either User Memory or Space Memory, and retains one stable identity as its content changes.
_Avoid_: MemoryRecord, database record

**User Memory**:
A Memory available across all Memory Spaces owned by one User. It is not limited to any one Memory Space.
_Avoid_: Global Memory, Space Memory

**Space Memory**:
A Memory shared by every Conversation belonging to one Memory Space. A Memory Space may be shared by several Conversations or dedicated to just one.
_Avoid_: User Memory, Conversation Memory, Task Memory

**Memory ID**:
The stable identity shared by a Memory and all events describing changes to it.
_Avoid_: Event ID

**Memory Event**:
An immutable history entry describing a successful ADD, UPDATE, or DELETE of a Memory. It does not represent an attempted or pending operation.
_Avoid_: Pending event, operation status

**Conversation**:
A sequence of related user and agent turns sharing one stable Conversation ID. Each Conversation belongs to exactly one Memory Space.
_Avoid_: Run

**Turn**:
A completed exchange within a Conversation, beginning with one user message and ending with the agent's final visible reply. Its transcript may include intermediate tool activity.
_Avoid_: Conversation, message

**Memory Space**:
A stable, user-owned namespace that groups Conversations and their shared Space Memories. In the current coding-agent product, one Memory Space represents one local workspace or code repository.
_Avoid_: Task, Conversation, run

**Todo Item**:
An ephemeral planning step used by the agent to track progress while executing work. A Todo Item is neither a Memory nor a Memory Space.
_Avoid_: Task

**Scope**:
The ownership and retrieval boundary that determines which Memories an operation may access. User Memory is bounded by its owning User; Space Memory is additionally bounded by one target Memory Space.
_Avoid_: Search metadata, optional filter

**Memory Context**:
The trusted User and Memory Space in which one Conversation is being processed. It bounds the possible Scopes but does not decide whether each extracted Memory becomes User Memory or Space Memory.
_Avoid_: Scope, filter

**Source Text**:
The authoritative human-readable content of a Memory from which retrieval representations can be derived.
_Avoid_: Embedding, tokenized text

**Retrieval Evaluation Run**:
A reproducible batch measurement of how well Memory retrieval identifies relevant evidence for a fixed dataset and configuration. It is separate from the deployed Django application and from an interactive Agent Turn.
_Avoid_: Deployment, production run, performance benchmark, Turn

**Evidence Session**:
A history session identified by an evaluation dataset as relevant to one retrieval query. Its evidence may occur in either user or agent-visible text.
_Avoid_: User-only evidence, Memory

**Haystack Session Occurrence**:
One position in an evaluation query's retrieval haystack, whether relevant or distractor. Multiple occurrences may share a Source Session ID and content while remaining separate retrieval candidates.
_Avoid_: Source Session ID, Memory

**Source Session ID**:
A dataset-provided label that relates retrieved Haystack Session Occurrences to evidence labels during scoring. It is not guaranteed to be unique within one query's haystack.
_Avoid_: Memory ID, Haystack Session Occurrence

**Abstention Case**:
An evaluation question intentionally lacking an Evidence Session and expecting the system not to answer from unsupported context.
_Avoid_: Retrieval miss, empty result

**Retrieval Baseline**:
A result artifact from a completed Retrieval Evaluation Run, tied to an exact source revision with no uncommitted changes, that serves as the comparison point for later retrieval changes. It is measured before quality regression thresholds are chosen.
_Avoid_: Quality threshold, performance benchmark

**LongMemEval Retrieval Baseline**:
A Retrieval Baseline produced by this project's retrievers on the official cleaned LongMemEval-S data using the official retrieval indexing, eligibility, and scoring rules. It measures retrieval only and is not an end-to-end LongMemEval answer score or an official leaderboard result.
_Avoid_: LongMemEval QA score, official leaderboard score

**CUDA Retrieval Evaluation Run**:
A Retrieval Evaluation Run in which the substantive model computation for both dense encoding and reranking executes on the pinned GPU. A run that falls back to CPU for model computation is invalid rather than a slower equivalent.
_Avoid_: CUDA-capable run, CPU fallback

**Evaluation Cache**:
A disposable intermediate artifact from a Retrieval Evaluation Run that is reusable only while its dataset, models, and retrieval configuration have the same identity.
_Avoid_: Retrieval Baseline, application Memory

**Candidate Retrieval Stage**:
The first retrieval phase, which combines Scope-bounded E5 dense and BM25 rankings with reciprocal-rank fusion to produce an ordered candidate pool.
_Avoid_: E5 stage, Reranking Stage

**Reranking Stage**:
The second retrieval phase, which uses BGE to reorder a fixed candidate pool produced by the Candidate Retrieval Stage.
_Avoid_: Candidate Retrieval Stage, hybrid retrieval
