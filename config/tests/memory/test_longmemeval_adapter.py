import json
import tempfile
from pathlib import Path
from unittest import TestCase

from evals.memory_retrieval.longmemeval_adapter import (
    OFFICIAL_SCORED_QUESTION_TYPES,
    load_longmemeval,
    select_smoke_question_ids,
)


def _source_case(question_id, question_type, *, user_evidence=True):
    evidence_turn = (
        {"role": "user", "content": "user evidence", "has_answer": True}
        if user_evidence
        else {"role": "assistant", "content": "assistant evidence", "has_answer": True}
    )
    return {
        "question_id": question_id,
        "question_type": question_type,
        "question": f"question {question_id}",
        "answer": "answer",
        "question_date": "2024/01/02 (Tue) 00:00",
        "haystack_session_ids": [f"{question_id}-answer", f"{question_id}-other"],
        "haystack_dates": ["2024/01/01 (Mon) 00:00", "2023/12/31 (Sun) 00:00"],
        "haystack_sessions": [
            [
                evidence_turn,
                {"role": "assistant", "content": "assistant text"},
            ],
            [{"role": "user", "content": "other user text"}],
        ],
        "answer_session_ids": [f"{question_id}-answer"],
    }


class LongMemEvalAdapterTests(TestCase):
    def setUp(self):
        scored = [
            _source_case(f"scored-{index}", question_type)
            for index, question_type in enumerate(OFFICIAL_SCORED_QUESTION_TYPES)
        ]
        self.cases = [
            *scored,
            _source_case(
                "assistant-only",
                "single-session-assistant",
                user_evidence=False,
            ),
            _source_case("abstention_abs", "single-session-user"),
        ]
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "longmemeval.json"
        self.path.write_text(json.dumps(self.cases), encoding="utf-8")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_smoke_selection_covers_every_type_and_two_exclusions(self):
        selected = select_smoke_question_ids(self.path)

        self.assertEqual(len(selected), 8)
        self.assertEqual(selected[-2:], ("assistant-only", "abstention_abs"))

    def test_adapter_indexes_user_text_and_excludes_officially_unscored_cases(self):
        dataset = load_longmemeval(
            self.path,
            question_ids=select_smoke_question_ids(self.path),
        )

        self.assertEqual(
            dataset["stats"],
            {
                "source_cases": 8,
                "adapted_cases": 6,
                "skipped_abstention": 1,
                "skipped_without_user_evidence": 1,
            },
        )
        self.assertEqual(dataset["memories"][0]["text"], "user evidence")
        first_query = dataset["queries"][0]
        self.assertEqual(
            first_query["relevant_session_ids"],
            ["scored-0-answer"],
        )
        self.assertEqual(
            {case["reason"] for case in dataset["excluded_cases"]},
            {"abstention", "without-user-evidence"},
        )
