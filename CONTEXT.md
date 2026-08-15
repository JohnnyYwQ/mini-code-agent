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
