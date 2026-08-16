from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

from evals.memory_retrieval.artifact_io import atomic_write_json, sha256_file, utc_now
from evals.memory_retrieval.candidate_stage import (
    load_candidate_records,
    run_candidate_stage,
)
from evals.memory_retrieval.longmemeval_adapter import (
    OFFICIAL_SCORED_QUESTION_TYPES,
    load_longmemeval,
    select_smoke_question_ids,
)
from evals.memory_retrieval.official_metrics import evaluate_records
from evals.memory_retrieval.rerank_stage import (
    RERANKING_NAME,
    load_candidate_artifact,
    load_rerank_records,
    run_rerank_stage,
)

DEFAULT_CANDIDATE_COUNT = 50
DEFAULT_E5_BATCH_SIZE = 8
DEFAULT_BGE_BATCH_SIZE = 4
DEFAULT_BGE_MAX_LENGTH = 512
EXPECTED_FULL_SOURCE_CASES = 500
EXPECTED_FULL_STATS = {
    "source_cases": EXPECTED_FULL_SOURCE_CASES,
    "adapted_cases": 419,
    "skipped_abstention": 30,
    "skipped_without_user_evidence": 51,
}
PRIMARY_METRICS = (
    "recall_all@5",
    "ndcg_any@5",
    "recall_all@10",
    "ndcg_any@10",
)
RANKING_LABELS = {
    "e5": "E5",
    "bm25": "BM25",
    "rrf": "E5+BM25+RRF",
    RERANKING_NAME: "E5+BM25+RRF+BGE",
}
REPO_ROOT = Path(__file__).resolve().parents[3]


def _common_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="require all pinned model snapshots to exist locally",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the CUDA-only LongMemEval retrieval baseline in two processes"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    candidates = subparsers.add_parser(
        "candidates", help="materialize E5, BM25, and RRF candidates"
    )
    _common_parser(candidates)
    candidates.add_argument("--cache-root", required=True, type=Path)
    candidates.add_argument("--fastembed-cache", required=True, type=Path)
    candidates.add_argument(
        "--candidate-count", type=int, default=DEFAULT_CANDIDATE_COUNT
    )
    candidates.add_argument("--e5-batch-size", type=int, default=DEFAULT_E5_BATCH_SIZE)
    candidates.add_argument(
        "--smoke",
        action="store_true",
        help="run deterministic question-type and exclusion coverage",
    )

    rerank = subparsers.add_parser("rerank", help="rerank the frozen RRF candidates")
    _common_parser(rerank)
    rerank.add_argument("--cache-root", required=True, type=Path)
    rerank.add_argument("--huggingface-cache", required=True, type=Path)
    rerank.add_argument(
        "--candidate-manifest",
        type=Path,
        help="default: RUN_DIR/candidate-stage.json",
    )
    rerank.add_argument("--bge-batch-size", type=int, default=DEFAULT_BGE_BATCH_SIZE)
    rerank.add_argument("--bge-max-length", type=int, default=DEFAULT_BGE_MAX_LENGTH)
    return parser.parse_args()


def _load_dataset(dataset_path: Path, *, smoke: bool) -> dict[str, Any]:
    question_ids = select_smoke_question_ids(dataset_path) if smoke else None
    dataset = load_longmemeval(dataset_path, question_ids=question_ids)
    if not dataset["queries"]:
        raise RuntimeError("LongMemEval contains no eligible retrieval cases")
    if smoke:
        stats = dataset["stats"]
        actual_types = {case["tags"][1] for case in dataset["queries"]}
        if actual_types != set(OFFICIAL_SCORED_QUESTION_TYPES):
            raise RuntimeError(
                f"smoke test does not cover all scored types: {sorted(actual_types)}"
            )
        if (
            stats["source_cases"] != 8
            or stats["adapted_cases"] != 6
            or stats["skipped_abstention"] != 1
            or stats["skipped_without_user_evidence"] != 1
        ):
            raise RuntimeError(f"unexpected smoke selection statistics: {stats}")
    elif dataset["stats"] != EXPECTED_FULL_STATS:
        raise RuntimeError(
            f"unexpected full LongMemEval selection statistics: {dataset['stats']}"
        )
    return dataset


def _metric_reports(
    records: list[dict[str, Any]], ranking_names: tuple[str, ...]
) -> dict[str, Any]:
    return {
        RANKING_LABELS[name]: evaluate_records(records, ranking_name=name)
        for name in ranking_names
    }


def _print_metrics(reports: dict[str, Any]) -> None:
    print("\nLongMemEval official-formula session retrieval metrics")
    print(
        f"{'retriever':<24} {'RecallAll@5':>12} {'NDCG@5':>10} "
        f"{'RecallAll@10':>13} {'NDCG@10':>11}"
    )
    for label, report in reports.items():
        metrics = report["overall"]
        print(
            f"{label:<24} "
            f"{metrics['recall_all@5']:>11.2%} "
            f"{metrics['ndcg_any@5']:>9.2%} "
            f"{metrics['recall_all@10']:>12.2%} "
            f"{metrics['ndcg_any@10']:>10.2%}"
        )


def _git_metadata(repo_root: Path) -> dict[str, Any]:
    def run(*arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    try:
        commit = run("rev-parse", "HEAD")
        branch = run("rev-parse", "--abbrev-ref", "HEAD")
        status = run("status", "--porcelain=v1", "--untracked-files=all")
    except (OSError, subprocess.CalledProcessError) as exc:
        return {
            "commit": "unknown",
            "branch": "unknown",
            "clean": False,
            "error": str(exc),
        }
    return {
        "commit": commit,
        "branch": branch,
        "clean": not bool(status),
        "status": status.splitlines(),
    }


def _run_candidates(args: argparse.Namespace) -> None:
    dataset = _load_dataset(args.dataset, smoke=args.smoke)
    manifest = run_candidate_stage(
        dataset=dataset,
        dataset_path=args.dataset,
        cache_root=args.cache_root,
        run_dir=args.run_dir,
        fastembed_cache=args.fastembed_cache,
        candidate_count=args.candidate_count,
        e5_batch_size=args.e5_batch_size,
        local_files_only=args.offline,
    )
    _, records = load_candidate_records(args.run_dir / "candidate-stage.json")
    reports = _metric_reports(records, ("e5", "bm25", "rrf"))
    atomic_write_json(
        args.run_dir / "candidate-metrics.json",
        {
            "schema": 1,
            "generated_at": utc_now(),
            "candidate_cache_key": manifest["cache_key"],
            "dataset_stats": manifest["dataset_stats"],
            "excluded_cases": manifest["excluded_cases"],
            "reports": reports,
        },
    )
    _print_metrics(reports)
    print(f"\nCandidate manifest: {args.run_dir / 'candidate-stage.json'}")


def _baseline(
    *,
    dataset_path: Path,
    candidate_manifest: dict[str, Any],
    rerank_manifest: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    git = _git_metadata(REPO_ROOT)
    reports = _metric_reports(records, ("e5", "bm25", "rrf", RERANKING_NAME))
    return {
        "schema": 1,
        "name": "official-data/official-metric LongMemEval retrieval baseline",
        "claim_scope": (
            "Retrieval-only baseline on the official cleaned LongMemEval-S data "
            "and official session-level metrics; not an official leaderboard score."
        ),
        "generated_at": utc_now(),
        "selection": (
            "full"
            if candidate_manifest["dataset_stats"]["source_cases"]
            == EXPECTED_FULL_SOURCE_CASES
            else "smoke"
        ),
        "qualification": "formal" if git["clean"] else "provisional",
        "git": git,
        "dataset": {
            "path": str(dataset_path.resolve()),
            "sha256": sha256_file(dataset_path),
            "stats": candidate_manifest["dataset_stats"],
            "excluded_cases": candidate_manifest["excluded_cases"],
        },
        "protocol": {
            "granularity": "session",
            "indexed_roles": ["user"],
            "corpus_boundary": "question",
            "excluded_from_aggregate": ["abstention", "without-user-evidence"],
            "primary_metrics": list(PRIMARY_METRICS),
        },
        "candidate_stage": {
            "cache_key": candidate_manifest["cache_key"],
            "identity": candidate_manifest["identity"],
            "runtime": candidate_manifest["runtime"],
        },
        "rerank_stage": {
            "cache_key": rerank_manifest["cache_key"],
            "identity": rerank_manifest["identity"],
            "runtime": rerank_manifest["runtime"],
        },
        "reports": reports,
    }


def _run_rerank(args: argparse.Namespace) -> None:
    candidate_manifest_path = (
        args.candidate_manifest or args.run_dir / "candidate-stage.json"
    )
    candidate_manifest, _ = load_candidate_artifact(candidate_manifest_path)
    question_ids = tuple(candidate_manifest["identity"]["dataset"]["question_ids"])
    dataset = load_longmemeval(args.dataset, question_ids=question_ids)
    manifest = run_rerank_stage(
        dataset=dataset,
        dataset_path=args.dataset,
        candidate_manifest_path=candidate_manifest_path,
        cache_root=args.cache_root,
        run_dir=args.run_dir,
        huggingface_cache=args.huggingface_cache,
        batch_size=args.bge_batch_size,
        max_length=args.bge_max_length,
        local_files_only=args.offline,
    )
    _, records = load_rerank_records(args.run_dir / "rerank-stage.json")
    baseline = _baseline(
        dataset_path=args.dataset,
        candidate_manifest=candidate_manifest,
        rerank_manifest=manifest,
        records=records,
    )
    baseline_path = args.run_dir / "baseline.json"
    atomic_write_json(baseline_path, baseline)
    _print_metrics(baseline["reports"])
    print(f"\nBaseline qualification: {baseline['qualification']}")
    print(f"Baseline: {baseline_path}")


def main() -> None:
    args = _parse_args()
    if args.command == "candidates":
        _run_candidates(args)
    elif args.command == "rerank":
        _run_rerank(args)
    else:
        raise AssertionError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    main()
