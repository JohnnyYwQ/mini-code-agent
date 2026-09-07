from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tqdm import tqdm

EVAL_ROOT = Path(__file__).resolve().parent
CONFIG_ROOT = EVAL_ROOT.parents[1]
for import_root in (EVAL_ROOT, CONFIG_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import jieba  # type: ignore[import-untyped]  # noqa: E402
from core.memory.bge_reranker import (  # noqa: E402
    DEFAULT_BGE_RERANKER_MODEL,
    BGEReranker,
)
from core.memory.embedder import (  # noqa: E402
    MULTILINGUAL_E5_BASE_DIMENSION,
    FastEmbedBM25Encoder,
    build_multilingual_e5_base_encoder,
)
from core.memory.flashrank_reranker import (  # noqa: E402
    DEFAULT_FLASHRANK_MODEL,
    FlashRankReranker,
)
from core.memory.memory import Memory, MemoryContext  # noqa: E402
from core.memory.qdrant_store import QdrantStore  # noqa: E402
from core.memory.reranker import MemoryReranker  # noqa: E402
from fastembed import SparseTextEmbedding  # noqa: E402
from longmemeval_adapter import load_longmemeval  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402

CASES_PATH = Path(__file__).with_name("cases.json")
LIMIT = 5


class UnusedMemoryExtractor:
    def extract(self, **_: Any) -> list[Any]:
        raise AssertionError("retrieval evaluation must not extract memories")


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    tags: tuple[str, ...]
    relevant_ids: tuple[str, ...]
    retrieved_ids: tuple[str, ...]
    hit_at_1: float
    recall_at_5: float
    mrr_at_5: float
    scope_leak_rate: float


@dataclass(frozen=True, slots=True)
class EvalReranker:
    name: str
    model_name: str | None
    adapter: MemoryReranker | None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Memory.recall retrieval")
    parser.add_argument(
        "--longmemeval",
        type=Path,
        metavar="PATH",
        help="load a LongMemEval JSON dataset instead of the built-in cases",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        metavar="N",
        help="adapt at most N scored LongMemEval cases",
    )
    parser.add_argument(
        "--reranker",
        choices=("none", "bge", "flashrank"),
        action="append",
        dest="rerankers",
        help="reranking backend; repeat to compare (default: none)",
    )
    args = parser.parse_args()
    if args.max_cases is not None and args.longmemeval is None:
        parser.error("--max-cases requires --longmemeval")
    if args.max_cases is not None and args.max_cases <= 0:
        parser.error("--max-cases must be greater than zero")
    args.rerankers = args.rerankers or ["none"]
    if len(args.rerankers) != len(set(args.rerankers)):
        parser.error("--reranker values must not be repeated")
    return args


def _load_dataset(args: argparse.Namespace) -> dict[str, Any]:
    if args.longmemeval is not None:
        return load_longmemeval(
            args.longmemeval,
            max_cases=args.max_cases,
        )
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def _select_reranker(name: str) -> EvalReranker:
    if name == "none":
        return EvalReranker(name="none", model_name=None, adapter=None)
    if name == "bge":
        return EvalReranker(
            name="bge",
            model_name=DEFAULT_BGE_RERANKER_MODEL,
            adapter=BGEReranker(),
        )
    if name == "flashrank":
        return EvalReranker(
            name="flashrank",
            model_name=DEFAULT_FLASHRANK_MODEL,
            adapter=FlashRankReranker(),
        )
    raise ValueError(f"unsupported reranker: {name}")


def _build_eval_memory(*, reranker: MemoryReranker | None) -> Memory:
    jieba.setLogLevel(logging.WARNING)
    dense_encoder = build_multilingual_e5_base_encoder()
    bm25_encoder = FastEmbedBM25Encoder(
        model=SparseTextEmbedding(model_name="Qdrant/bm25"),
        chinese_segmenter=jieba.cut,
    )
    vector_store = QdrantStore(
        client=QdrantClient(":memory:"),
        collection_name="memory_retrieval_eval",
        dimension=MULTILINGUAL_E5_BASE_DIMENSION,
        bm25_encoder=bm25_encoder,
    )
    return Memory(
        extractor=UnusedMemoryExtractor(),
        dense_encoder=dense_encoder,
        vector_store=vector_store,
        reranker=reranker,
    )


def _is_in_scope(eval_memory: dict[str, Any], context: MemoryContext) -> bool:
    return eval_memory["user_id"] == context.user_id and (
        eval_memory["space_id"] is None or eval_memory["space_id"] == context.space_id
    )


def _evaluate_case(
    *,
    memory: Memory,
    case: dict[str, Any],
    memory_by_id: dict[str, dict[str, Any]],
    rerank: bool,
) -> CaseResult:
    context = MemoryContext(**case["context"])
    results = memory.recall(
        query=case["query"],
        context=context,
        limit=LIMIT,
        rerank=rerank,
    )
    retrieved_ids = tuple(result.id for result in results)
    relevant_ids = tuple(case["relevant_memory_ids"])
    relevant_set = set(relevant_ids)

    first_relevant_rank = next(
        (
            rank
            for rank, memory_id in enumerate(retrieved_ids, start=1)
            if memory_id in relevant_set
        ),
        None,
    )
    leaked_count = sum(
        memory_id not in memory_by_id
        or not _is_in_scope(memory_by_id[memory_id], context)
        for memory_id in retrieved_ids
    )

    return CaseResult(
        case_id=case["id"],
        tags=tuple(case["tags"]),
        relevant_ids=relevant_ids,
        retrieved_ids=retrieved_ids,
        hit_at_1=float(bool(retrieved_ids and retrieved_ids[0] in relevant_set)),
        recall_at_5=len(relevant_set.intersection(retrieved_ids)) / len(relevant_set),
        mrr_at_5=0.0 if first_relevant_rank is None else 1 / first_relevant_rank,
        scope_leak_rate=(leaked_count / len(retrieved_ids) if retrieved_ids else 0.0),
    )


def _mean_metrics(results: list[CaseResult]) -> dict[str, float]:
    return {
        "Hit@1": sum(result.hit_at_1 for result in results) / len(results),
        "Recall@5": sum(result.recall_at_5 for result in results) / len(results),
        "MRR@5": sum(result.mrr_at_5 for result in results) / len(results),
        "ScopeLeakRate": sum(result.scope_leak_rate for result in results)
        / len(results),
    }


def _dcg(relevances: list[float]) -> float:
    if not relevances:
        return 0.0
    return relevances[0] + sum(
        relevance / math.log2(rank)
        for rank, relevance in enumerate(relevances[1:], start=2)
    )


def _longmemeval_metrics(results: list[CaseResult]) -> dict[str, float]:
    recall_any_values: list[float] = []
    recall_all_values: list[float] = []
    ndcg_values: list[float] = []

    for result in results:
        relevant_ids = set(result.relevant_ids)
        retrieved_ids = result.retrieved_ids[:LIMIT]
        retrieved_id_set = set(retrieved_ids)
        recall_any_values.append(float(bool(relevant_ids & retrieved_id_set)))
        recall_all_values.append(float(relevant_ids <= retrieved_id_set))

        actual_relevances = [
            float(memory_id in relevant_ids) for memory_id in retrieved_ids
        ]
        ideal_relevances = [1.0] * min(len(relevant_ids), LIMIT)
        ideal_dcg = _dcg(ideal_relevances)
        ndcg_values.append(_dcg(actual_relevances) / ideal_dcg if ideal_dcg else 0.0)

    count = len(results)
    return {
        "RecallAny@5": sum(recall_any_values) / count,
        "RecallAll@5": sum(recall_all_values) / count,
        "NDCG@5": sum(ndcg_values) / count,
    }


def _print_report(
    results: list[CaseResult],
    *,
    reranker: EvalReranker,
) -> None:
    groups: dict[str, list[CaseResult]] = defaultdict(list)
    groups["overall"] = results
    for result in results:
        for tag in result.tags:
            groups[tag].append(result)

    model_name = reranker.model_name or "none"
    print(
        f"Memory retrieval eval: {len(results)} cases, limit={LIMIT}, "
        f"reranker={reranker.name}, model={model_name}"
    )
    print(
        f"{'group':<18} {'cases':>5} {'Hit@1':>9} {'Recall@5':>10} "
        f"{'MRR@5':>9} {'ScopeLeak':>11}"
    )
    for group_name in ["overall", *sorted(groups.keys() - {"overall"})]:
        group_results = groups[group_name]
        metrics = _mean_metrics(group_results)
        print(
            f"{group_name:<18} {len(group_results):>5} "
            f"{metrics['Hit@1']:>8.1%} {metrics['Recall@5']:>9.1%} "
            f"{metrics['MRR@5']:>8.1%} "
            f"{metrics['ScopeLeakRate']:>10.1%}"
        )

    imperfect = [
        result
        for result in results
        if result.recall_at_5 < 1.0 or result.scope_leak_rate > 0.0
    ]
    if imperfect:
        print("\nCases needing inspection:")
        for result in imperfect:
            print(
                f"- {result.case_id}: relevant={list(result.relevant_ids)}, "
                f"retrieved={list(result.retrieved_ids)}"
            )


def _print_longmemeval_report(results: list[CaseResult]) -> None:
    groups: dict[str, list[CaseResult]] = defaultdict(list)
    groups["overall"] = results
    non_question_type_tags = {"longmemeval", "single", "multi"}
    for result in results:
        for tag in result.tags:
            if tag not in non_question_type_tags:
                groups[tag].append(result)

    print(f"\nLongMemEval official session metrics: k={LIMIT}")
    print(
        f"{'group':<30} {'cases':>5} {'RecallAny@5':>13} "
        f"{'RecallAll@5':>13} {'NDCG@5':>9}"
    )
    for group_name in ["overall", *sorted(groups.keys() - {"overall"})]:
        group_results = groups[group_name]
        metrics = _longmemeval_metrics(group_results)
        print(
            f"{group_name:<30} {len(group_results):>5} "
            f"{metrics['RecallAny@5']:>12.1%} "
            f"{metrics['RecallAll@5']:>12.1%} "
            f"{metrics['NDCG@5']:>8.1%}"
        )


def main() -> None:
    args = _parse_args()
    rerankers = [_select_reranker(name) for name in args.rerankers]
    dataset = _load_dataset(args)
    memories = dataset["memories"]
    if not dataset["queries"]:
        raise ValueError("dataset contains no retrieval cases")

    if "stats" in dataset:
        stats = dataset["stats"]
        print(
            "LongMemEval adapter: "
            f"adapted={stats['adapted_cases']}, "
            f"skipped_abstention={stats['skipped_abstention']}, "
            "skipped_without_user_evidence="
            f"{stats['skipped_without_user_evidence']}"
        )

    memory_by_id = {memory["id"]: memory for memory in memories}
    memory = _build_eval_memory(reranker=None)

    try:
        for record in tqdm(
            memories,
            desc="Indexing memories",
            unit="memory",
            dynamic_ncols=True,
            disable=None,
        ):
            payload = {
                "data": record["text"],
                "user_id": record["user_id"],
            }
            if record["space_id"] is not None:
                payload["space_id"] = record["space_id"]
            memory.vector_store.upsert(
                memory_id=record["id"],
                vector=memory.dense_encoder.encode_document(record["text"]),
                payload=payload,
            )

        for index, reranker in enumerate(rerankers):
            if index:
                print()
            memory.reranker = reranker.adapter
            results = [
                _evaluate_case(
                    memory=memory,
                    case=case,
                    memory_by_id=memory_by_id,
                    rerank=reranker.adapter is not None,
                )
                for case in tqdm(
                    dataset["queries"],
                    desc=f"Evaluating {reranker.name}",
                    unit="case",
                    dynamic_ncols=True,
                    disable=None,
                )
            ]
            _print_report(results, reranker=reranker)
            if args.longmemeval is not None:
                _print_longmemeval_report(results)
    finally:
        memory.close()


if __name__ == "__main__":
    main()
