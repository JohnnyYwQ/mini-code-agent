from __future__ import annotations

import importlib.metadata as metadata
import json
import math
import os
from pathlib import Path
from typing import Any

from core.memory.bge_reranker import BGEReranker
from core.memory.vector_store import MemorySearchResult
from evals.memory_retrieval.artifact_io import (
    atomic_write_json,
    canonical_digest,
    read_resumable_jsonl,
    rewrite_jsonl,
    sha256_file,
    utc_now,
)
from evals.memory_retrieval.cuda_host import require_pinned_cuda_host
from evals.memory_retrieval.model_snapshots import BGE_SNAPSHOT, resolve_snapshot
from tqdm import tqdm

RERANK_STAGE_SCHEMA = 1
RERANKING_NAME = "rrf_bge"
EXPECTED_RERANK_DISTRIBUTIONS = {
    "FlagEmbedding": "1.4.0",
    "torch": "2.6.0+cu124",
    "transformers": "4.57.6",
}


def _distribution_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def require_cuda_rerank_environment() -> tuple[dict[str, str], dict[str, Any]]:
    versions: dict[str, str] = {}
    for name, expected in EXPECTED_RERANK_DISTRIBUTIONS.items():
        actual = _distribution_version(name)
        if actual != expected:
            raise RuntimeError(f"expected {name}=={expected}, found {actual}")
        versions[name] = actual

    return versions, require_pinned_cuda_host()


def _source_digest() -> str:
    source_paths = (
        Path(__file__),
        Path(__file__).with_name("artifact_io.py"),
        Path(__file__).with_name("cuda_host.py"),
        Path(__file__).with_name("official_metrics.py"),
        Path(__file__).parents[2] / "core" / "memory" / "bge_reranker.py",
    )
    repo_root = Path(__file__).parents[3]
    return canonical_digest(
        {str(path.relative_to(repo_root)): sha256_file(path) for path in source_paths}
    )


def load_candidate_artifact(
    manifest_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        raise RuntimeError(f"candidate stage is not complete: {manifest_path}")
    artifact_path = Path(manifest["artifact_path"])
    records_by_id = read_resumable_jsonl(artifact_path)
    question_ids = manifest["identity"]["dataset"]["question_ids"]
    if set(records_by_id) != set(question_ids):
        raise RuntimeError("candidate artifact case ids do not match its manifest")
    if len(records_by_id) != manifest.get("record_count"):
        raise RuntimeError(
            "candidate artifact record count does not match its manifest"
        )
    return manifest, [records_by_id[question_id] for question_id in question_ids]


def build_rerank_identity(
    *,
    candidate_manifest: dict[str, Any],
    dataset_path: Path,
    batch_size: int,
    max_length: int,
    dependency_versions: dict[str, str],
) -> dict[str, Any]:
    if batch_size <= 0:
        raise ValueError("BGE batch_size must be greater than zero")
    if max_length <= 0:
        raise ValueError("BGE max_length must be greater than zero")
    dataset_sha256 = sha256_file(dataset_path)
    expected_dataset_sha256 = candidate_manifest["identity"]["dataset"]["sha256"]
    if dataset_sha256 != expected_dataset_sha256:
        raise RuntimeError(
            "LongMemEval dataset changed after candidate retrieval: "
            f"{dataset_sha256} != {expected_dataset_sha256}"
        )
    return {
        "schema": RERANK_STAGE_SCHEMA,
        "candidate_cache_key": candidate_manifest["cache_key"],
        "question_ids": candidate_manifest["identity"]["dataset"]["question_ids"],
        "dataset_sha256": dataset_sha256,
        "model": {
            "repo_id": BGE_SNAPSHOT.repo_id,
            "revision": BGE_SNAPSHOT.revision,
            "device": "cuda:0",
            "dtype": "float16",
            "batch_size": batch_size,
            "max_length": max_length,
            "input_ranking": "rrf",
        },
        "dependencies": dependency_versions,
        "uv_lock_sha256": sha256_file(Path(__file__).parents[3] / "uv.lock"),
        "source_sha256": _source_digest(),
    }


def _memory_texts_by_case(dataset: dict[str, Any]) -> dict[str, dict[str, str]]:
    case_by_space = {
        case["context"]["space_id"]: case["id"] for case in dataset["queries"]
    }
    result: dict[str, dict[str, str]] = {case["id"]: {} for case in dataset["queries"]}
    for memory in dataset["memories"]:
        case_id = case_by_space.get(memory["space_id"])
        if case_id is None:
            raise RuntimeError(f"memory has unknown evaluation space: {memory}")
        session_id = memory["source_session_id"]
        if session_id in result[case_id]:
            raise RuntimeError(f"{case_id}: duplicate source session id {session_id}")
        result[case_id][session_id] = memory["text"]
    return result


def _rerank_record(
    *,
    candidate_record: dict[str, Any],
    memory_text_by_session: dict[str, str],
    reranker: BGEReranker,
) -> dict[str, Any]:
    if set(candidate_record["corpus_ids"]) != set(memory_text_by_session):
        raise RuntimeError(
            f"{candidate_record['case_id']}: candidate corpus does not match dataset"
        )
    rrf_items = candidate_record["rankings"]["rrf"]
    candidates = [
        MemorySearchResult(
            id=item["id"],
            data=memory_text_by_session[item["id"]],
            scope="space",
            score=float(item["score"]),
            metadata={},
        )
        for item in rrf_items
    ]
    ranked = reranker.rerank(
        query=candidate_record["query"],
        candidates=candidates,
        limit=len(candidates),
    )
    if len(ranked) != len(candidates):
        raise RuntimeError(
            f"{candidate_record['case_id']}: BGE did not return every candidate"
        )
    if any(not math.isfinite(item.score) for item in ranked):
        raise RuntimeError(
            f"{candidate_record['case_id']}: BGE returned non-finite scores"
        )
    rankings = dict(candidate_record["rankings"])
    rankings[RERANKING_NAME] = [{"id": item.id, "score": item.score} for item in ranked]
    return {**candidate_record, "schema": RERANK_STAGE_SCHEMA, "rankings": rankings}


def run_rerank_stage(
    *,
    dataset: dict[str, Any],
    dataset_path: Path,
    candidate_manifest_path: Path,
    cache_root: Path,
    run_dir: Path,
    huggingface_cache: Path,
    batch_size: int,
    max_length: int,
    local_files_only: bool,
) -> dict[str, Any]:
    dependency_versions, runtime = require_cuda_rerank_environment()
    candidate_manifest, candidate_records = load_candidate_artifact(
        candidate_manifest_path
    )
    question_ids = candidate_manifest["identity"]["dataset"]["question_ids"]
    if [case["id"] for case in dataset["queries"]] != question_ids:
        raise RuntimeError(
            "rerank dataset case order does not match candidate manifest"
        )

    identity = build_rerank_identity(
        candidate_manifest=candidate_manifest,
        dataset_path=dataset_path,
        batch_size=batch_size,
        max_length=max_length,
        dependency_versions=dependency_versions,
    )
    cache_key = canonical_digest(identity)
    cache_dir = cache_root / cache_key
    records_path = cache_dir / "reranked.jsonl"
    cache_manifest_path = cache_dir / "manifest.json"
    run_manifest_path = run_dir / "rerank-stage.json"
    cache_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    record_by_id = read_resumable_jsonl(records_path)
    unexpected_ids = set(record_by_id).difference(question_ids)
    if unexpected_ids:
        raise RuntimeError(f"rerank cache contains unexpected cases: {unexpected_ids}")

    started_at = utc_now()
    previous_manifest: dict[str, Any] = {}
    if cache_manifest_path.exists():
        previous_manifest = json.loads(cache_manifest_path.read_text(encoding="utf-8"))
        if previous_manifest.get("cache_key") == cache_key:
            started_at = previous_manifest.get("started_at", started_at)
            runtime.update(previous_manifest.get("runtime", {}))
    atomic_write_json(
        cache_manifest_path,
        {
            "status": "in_progress",
            "cache_key": cache_key,
            "identity": identity,
            "runtime": runtime,
            "started_at": started_at,
            "completed_case_ids": list(record_by_id),
        },
    )

    if len(record_by_id) != len(question_ids):
        bge_path = resolve_snapshot(
            BGE_SNAPSHOT,
            cache_dir=huggingface_cache,
            local_files_only=local_files_only,
        )
        reranker = BGEReranker(
            model_name=str(bge_path),
            use_fp16=True,
            device="cuda:0",
            batch_size=batch_size,
            max_length=max_length,
            require_cuda=True,
        )
        text_by_case = _memory_texts_by_case(dataset)
        candidate_record_by_id = {
            record["case_id"]: record for record in candidate_records
        }
        with records_path.open("a", encoding="utf-8") as output:
            for question_id in tqdm(
                question_ids,
                desc="BGE reranking",
                unit="case",
                dynamic_ncols=True,
            ):
                if question_id in record_by_id:
                    continue
                record = _rerank_record(
                    candidate_record=candidate_record_by_id[question_id],
                    memory_text_by_session=text_by_case[question_id],
                    reranker=reranker,
                )
                runtime.update(reranker.runtime)
                output.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        sort_keys=True,
                        allow_nan=False,
                    )
                    + "\n"
                )
                output.flush()
                os.fsync(output.fileno())
                record_by_id[question_id] = record
                atomic_write_json(
                    cache_manifest_path,
                    {
                        "status": "in_progress",
                        "cache_key": cache_key,
                        "identity": identity,
                        "runtime": runtime,
                        "started_at": started_at,
                        "completed_case_ids": list(record_by_id),
                    },
                )

    if "parameter_devices" not in runtime:
        raise RuntimeError("rerank cache lacks verified BGE CUDA runtime evidence")
    ordered_records = [record_by_id[question_id] for question_id in question_ids]
    rewrite_jsonl(records_path, ordered_records)
    manifest = {
        "status": "complete",
        "cache_key": cache_key,
        "identity": identity,
        "runtime": runtime,
        "started_at": started_at,
        "finished_at": utc_now(),
        "record_count": len(ordered_records),
        "dataset_stats": candidate_manifest["dataset_stats"],
        "excluded_cases": candidate_manifest["excluded_cases"],
        "artifact_path": str(records_path.resolve()),
    }
    atomic_write_json(cache_manifest_path, manifest)
    atomic_write_json(run_manifest_path, manifest)
    return manifest


def load_rerank_records(
    manifest_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        raise RuntimeError(f"rerank stage is not complete: {manifest_path}")
    records_by_id = read_resumable_jsonl(Path(manifest["artifact_path"]))
    expected_count = manifest.get("record_count")
    if len(records_by_id) != expected_count:
        raise RuntimeError("rerank artifact record count does not match its manifest")
    ordered_ids = manifest["identity"]["question_ids"]
    if set(records_by_id) != set(ordered_ids):
        raise RuntimeError("rerank artifact case ids do not match its manifest")
    return manifest, [records_by_id[question_id] for question_id in ordered_ids]
