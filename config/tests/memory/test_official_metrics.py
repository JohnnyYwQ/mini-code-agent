import math
from unittest import TestCase

from evals.memory_retrieval.official_metrics import (
    evaluate_ranking,
    evaluate_records,
)


class OfficialLongMemEvalMetricsTests(TestCase):
    def test_matches_official_recall_and_dcg_formula(self):
        metrics = evaluate_ranking(
            ["irrelevant", "target-b", "target-a"],
            ["target-a", "target-b"],
        )

        self.assertEqual(metrics["recall_any@5"], 1.0)
        self.assertEqual(metrics["recall_all@5"], 1.0)
        expected_dcg = (1.0 + 1 / math.log2(3)) / 2.0
        self.assertAlmostEqual(metrics["ndcg_any@5"], expected_dcg)
        self.assertEqual(metrics["recall_all@10"], 1.0)

    def test_recall_all_requires_every_relevant_session(self):
        metrics = evaluate_ranking(["target-a"], ["target-a", "target-b"])

        self.assertEqual(metrics["recall_any@5"], 1.0)
        self.assertEqual(metrics["recall_all@5"], 0.0)
        self.assertEqual(metrics["ndcg_any@5"], 0.5)

    def test_aggregates_overall_and_question_type_metrics(self):
        records = [
            {
                "case_id": "one",
                "question_type": "single-session-user",
                "relevant_ids": ["a"],
                "rankings": {"e5": [{"id": "a", "score": 1.0}]},
            },
            {
                "case_id": "two",
                "question_type": "multi-session",
                "relevant_ids": ["b"],
                "rankings": {"e5": [{"id": "x", "score": 1.0}]},
            },
        ]

        report = evaluate_records(records, ranking_name="e5")

        self.assertEqual(report["overall"]["recall_all@5"], 0.5)
        self.assertEqual(
            report["by_question_type"]["single-session-user"]["recall_all@10"],
            1.0,
        )
