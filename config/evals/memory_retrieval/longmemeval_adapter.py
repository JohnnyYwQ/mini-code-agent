from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

LONGMEMEVAL_USER_ID = "longmemeval"


def _memory_id(
    *,
    question_id: str,
    session_index: int,
    session_id: str,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "https://github.com/xiaowu0162/LongMemEval/"
            f"{question_id}/{session_index}/{session_id}",
        )
    )


def _user_text(*, question_id: str, session: list[dict[str, Any]]) -> str:
    contents: list[str] = []
    for turn in session:
        if turn.get("role") != "user":
            continue
        content = turn.get("content")
        if not isinstance(content, str):
            raise ValueError(f"{question_id}: user turn content must be a string")
        contents.append(content)
    return " ".join(contents)


def load_longmemeval(
    path: str | Path,
    *,
    max_cases: int | None = None,
) -> dict[str, Any]:
    """Adapt LongMemEval into the dataset shape consumed by retrieval evals.

    Sessions are indexed at the official flat-session granularity: only user
    messages are joined into each candidate document. Abstention questions and
    questions without user-side evidence are excluded from retrieval scoring.
    """
    if max_cases is not None and max_cases <= 0:
        raise ValueError("max_cases must be greater than zero")

    source_path = Path(path)
    with source_path.open(encoding="utf-8") as source_file:
        source_cases = json.load(source_file)
    if not isinstance(source_cases, list):
        raise ValueError("LongMemEval dataset must contain a JSON list")

    memories: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    seen_question_ids: set[str] = set()
    skipped_abstention = 0
    skipped_without_user_evidence = 0

    for source_case in source_cases:
        question_id = source_case.get("question_id")
        if not isinstance(question_id, str) or not question_id:
            raise ValueError("LongMemEval question_id must be a non-empty string")
        if question_id in seen_question_ids:
            raise ValueError(f"duplicate LongMemEval question_id: {question_id}")
        seen_question_ids.add(question_id)

        if question_id.endswith("_abs"):
            skipped_abstention += 1
            continue

        session_ids = source_case.get("haystack_session_ids")
        sessions = source_case.get("haystack_sessions")
        session_dates = source_case.get("haystack_dates")
        if not all(
            isinstance(value, list) for value in (session_ids, sessions, session_dates)
        ):
            raise ValueError(f"{question_id}: haystack fields must be lists")
        if not len(session_ids) == len(sessions) == len(session_dates):
            raise ValueError(f"{question_id}: haystack fields must have equal lengths")
        answer_session_ids = source_case.get("answer_session_ids")
        if not isinstance(answer_session_ids, list):
            raise ValueError(f"{question_id}: answer_session_ids must be a list")
        answer_session_id_set = set(answer_session_ids)
        if not answer_session_id_set.issubset(set(session_ids)):
            raise ValueError(
                f"{question_id}: answer_session_ids must exist in the haystack"
            )

        user_evidence_indices = [
            session_index
            for session_index, session in enumerate(sessions)
            if any(
                turn.get("role") == "user" and turn.get("has_answer") is True
                for turn in session
            )
        ]
        if not user_evidence_indices:
            skipped_without_user_evidence += 1
            continue
        user_evidence_session_ids = {
            session_ids[session_index] for session_index in user_evidence_indices
        }
        if not user_evidence_session_ids.issubset(answer_session_id_set):
            raise ValueError(
                f"{question_id}: user-side evidence must belong to answer sessions"
            )

        question = source_case.get("question")
        question_type = source_case.get("question_type")
        if not isinstance(question, str) or not question:
            raise ValueError(f"{question_id}: question must be a non-empty string")
        if not isinstance(question_type, str) or not question_type:
            raise ValueError(f"{question_id}: question_type must be a non-empty string")

        space_id = f"longmemeval:{question_id}"
        memory_ids: list[str] = []
        for session_index, (session_id, session, session_date) in enumerate(
            zip(
                session_ids,
                sessions,
                session_dates,
                strict=True,
            )
        ):
            if not isinstance(session_id, str) or not session_id:
                raise ValueError(
                    f"{question_id}: session ids must be non-empty strings"
                )
            if not isinstance(session, list):
                raise ValueError(f"{question_id}: each session must be a list")
            memory_id = _memory_id(
                question_id=question_id,
                session_index=session_index,
                session_id=session_id,
            )
            memory_ids.append(memory_id)
            memories.append(
                {
                    "id": memory_id,
                    "text": _user_text(
                        question_id=question_id,
                        session=session,
                    ),
                    "user_id": LONGMEMEVAL_USER_ID,
                    "space_id": space_id,
                    "source_session_id": session_id,
                    "source_date": session_date,
                }
            )

        relevant_memory_ids = [
            memory_ids[session_index] for session_index in user_evidence_indices
        ]
        queries.append(
            {
                "id": question_id,
                "query": question,
                "context": {
                    "user_id": LONGMEMEVAL_USER_ID,
                    "space_id": space_id,
                },
                "relevant_memory_ids": relevant_memory_ids,
                "tags": [
                    "longmemeval",
                    question_type,
                    "single" if len(relevant_memory_ids) == 1 else "multi",
                ],
                "question_date": source_case.get("question_date"),
                "reference_answer": source_case.get("answer"),
            }
        )

        if max_cases is not None and len(queries) >= max_cases:
            break

    return {
        "version": 1,
        "description": "LongMemEval flat-session retrieval cases.",
        "source": {
            "name": "LongMemEval",
            "path": str(source_path),
            "granularity": "session",
            "indexed_roles": ["user"],
        },
        "stats": {
            "adapted_cases": len(queries),
            "skipped_abstention": skipped_abstention,
            "skipped_without_user_evidence": skipped_without_user_evidence,
        },
        "memories": memories,
        "queries": queries,
    }
