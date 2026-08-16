from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

OFFICIAL_CUTOFFS = (5, 10)


def _dcg(relevances: Sequence[float], *, cutoff: int) -> float:
    selected = relevances[:cutoff]
    if not selected:
        return 0.0
    return selected[0] + sum(
        relevance / math.log2(index + 1)
        for index, relevance in enumerate(selected[1:], start=1)
    )


def evaluate_ranking(
    retrieved_ids: Sequence[str],
    relevant_ids: Sequence[str],
    *,
    cutoffs: Sequence[int] = OFFICIAL_CUTOFFS,
) -> dict[str, float]:
    """Apply LongMemEval's official session-level retrieval formulas."""
    if not relevant_ids:
        raise ValueError("official retrieval metrics require at least one target")
    if len(set(relevant_ids)) != len(relevant_ids):
        raise ValueError("relevant_ids must not contain duplicates")
    if len(set(retrieved_ids)) != len(retrieved_ids):
        raise ValueError("retrieved_ids must not contain duplicates")

    relevant_set = set(relevant_ids)
    ideal_relevances = [1.0] * len(relevant_set)
    metrics: dict[str, float] = {}
    for cutoff in cutoffs:
        if cutoff <= 0:
            raise ValueError("metric cutoffs must be greater than zero")
        selected_ids = retrieved_ids[:cutoff]
        recalled = relevant_set.intersection(selected_ids)
        actual_relevances = [
            float(retrieved_id in relevant_set) for retrieved_id in selected_ids
        ]
        ideal_dcg = _dcg(ideal_relevances, cutoff=cutoff)
        metrics[f"recall_any@{cutoff}"] = float(bool(recalled))
        metrics[f"recall_all@{cutoff}"] = float(recalled == relevant_set)
        metrics[f"ndcg_any@{cutoff}"] = (
            _dcg(actual_relevances, cutoff=cutoff) / ideal_dcg if ideal_dcg else 0.0
        )
    return metrics


def mean_metrics(metrics: Iterable[dict[str, float]]) -> dict[str, float]:
    rows = list(metrics)
    if not rows:
        raise ValueError("cannot average an empty metric collection")
    keys = tuple(rows[0])
    if any(tuple(row) != keys for row in rows[1:]):
        raise ValueError("metric rows must contain the same ordered keys")
    return {key: sum(row[key] for row in rows) / len(rows) for key in keys}


def evaluate_records(
    records: Sequence[dict[str, Any]],
    *,
    ranking_name: str,
) -> dict[str, Any]:
    case_metrics: list[dict[str, Any]] = []
    metrics_by_type: dict[str, list[dict[str, float]]] = defaultdict(list)
    for record in records:
        retrieved_ids = [item["id"] for item in record["rankings"][ranking_name]]
        metrics = evaluate_ranking(retrieved_ids, record["relevant_ids"])
        question_type = record["question_type"]
        metrics_by_type[question_type].append(metrics)
        case_metrics.append(
            {
                "case_id": record["case_id"],
                "question_type": question_type,
                "metrics": metrics,
            }
        )

    return {
        "overall": mean_metrics(item["metrics"] for item in case_metrics),
        "by_question_type": {
            question_type: mean_metrics(type_metrics)
            for question_type, type_metrics in sorted(metrics_by_type.items())
        },
        "cases": case_metrics,
    }
