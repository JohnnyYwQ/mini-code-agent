from __future__ import annotations

import importlib.metadata as metadata
import json
import logging
import math
import os
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import jieba  # type: ignore[import-untyped]
import torch as _torch  # noqa: F401  # preload CUDA libraries before FastEmbed/ORT
from core.memory.embedder import (
    CUDA_EXECUTION_PROVIDER,
    MULTILINGUAL_E5_BASE_DIMENSION,
    FastEmbedBM25Encoder,
    FastEmbedE5Encoder,
    build_multilingual_e5_base_encoder,
)
from core.memory.qdrant_store import QdrantStore
from evals.memory_retrieval.artifact_io import (
    atomic_write_json,
    canonical_digest,
    read_resumable_jsonl,
    rewrite_jsonl,
    sha256_file,
    utc_now,
)
from evals.memory_retrieval.cuda_host import require_pinned_cuda_host
from evals.memory_retrieval.model_snapshots import (
    BM25_SNAPSHOT,
    E5_SNAPSHOT,
    resolve_snapshot,
)
from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient, models
from tqdm import tqdm

CANDIDATE_STAGE_SCHEMA = 2
RRF_RANK_CONSTANT = 60
MINIMUM_CANDIDATE_COUNT = 10
EXPECTED_CUDA_DISTRIBUTIONS = {
    "fastembed-gpu": "0.8.0",
    "onnxruntime-gpu": "1.26.0",
    "torch": "2.6.0+cu124",
}
FORBIDDEN_CUDA_DISTRIBUTIONS = ("fastembed", "onnxruntime")


def _distribution_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def require_cuda_candidate_environment() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name, expected in EXPECTED_CUDA_DISTRIBUTIONS.items():
        actual = _distribution_version(name)
        if actual != expected:
            raise RuntimeError(f"expected {name}=={expected}, found {actual}")
        versions[name] = actual
    for name in FORBIDDEN_CUDA_DISTRIBUTIONS:
        actual = _distribution_version(name)
        if actual is not None:
            raise RuntimeError(
                f"{name}=={actual} conflicts with the CUDA evaluation environment"
            )
    return versions


def inspect_cuda_runtime() -> dict[str, Any]:
    """Fail before retrieval unless both PyTorch and ONNX Runtime expose CUDA."""
    runtime = require_pinned_cuda_host()

    import onnxruntime as ort

    available_providers = tuple(ort.get_available_providers())
    if "CUDAExecutionProvider" not in available_providers:
        raise RuntimeError(
            "ONNX Runtime CUDAExecutionProvider is unavailable; "
            f"providers={available_providers}"
        )
    runtime.update(
        {
            "onnxruntime": ort.__version__,
            "onnxruntime_available_providers": list(available_providers),
        }
    )
    return runtime


def _has_verified_e5_cuda_execution(evidence: object) -> bool:
    if not isinstance(evidence, dict):
        return False
    providers = evidence.get("providers")
    cuda_compute_ops = evidence.get("cuda_compute_ops")
    cpu_compute_ops = evidence.get("cpu_compute_ops")
    return (
        evidence.get("device_id") == 0
        and isinstance(providers, list)
        and bool(providers)
        and providers[0] == CUDA_EXECUTION_PROVIDER
        and isinstance(cuda_compute_ops, list)
        and bool(cuda_compute_ops)
        and cpu_compute_ops == []
    )


def _source_digest() -> str:
    source_paths = (
        Path(__file__),
        Path(__file__).with_name("artifact_io.py"),
        Path(__file__).with_name("cuda_host.py"),
        Path(__file__).with_name("longmemeval_adapter.py"),
        Path(__file__).parents[2] / "core" / "memory" / "embedder.py",
        Path(__file__).parents[2] / "core" / "memory" / "qdrant_store.py",
    )
    return canonical_digest(
        {
            str(path.relative_to(Path(__file__).parents[3])): sha256_file(path)
            for path in source_paths
        }
    )


def build_candidate_identity(
    *,
    dataset_path: Path,
    question_ids: Sequence[str],
    candidate_count: int,
    e5_batch_size: int,
    dependency_versions: dict[str, str],
) -> dict[str, Any]:
    if candidate_count < MINIMUM_CANDIDATE_COUNT:
        raise ValueError(f"candidate_count must be at least {MINIMUM_CANDIDATE_COUNT}")
    if e5_batch_size <= 0:
        raise ValueError("e5_batch_size must be greater than zero")
    return {
        "schema": CANDIDATE_STAGE_SCHEMA,
        "dataset": {
            "path_name": dataset_path.name,
            "sha256": sha256_file(dataset_path),
            "question_ids": list(question_ids),
        },
        "protocol": {
            "granularity": "session",
            "indexed_roles": ["user"],
            "corpus_boundary": "question",
            "candidate_count": candidate_count,
            "rrf_rank_constant": RRF_RANK_CONSTANT,
            "e5_batch_size": e5_batch_size,
        },
        "models": {
            "e5": {
                "repo_id": E5_SNAPSHOT.repo_id,
                "revision": E5_SNAPSHOT.revision,
                "dimension": MULTILINGUAL_E5_BASE_DIMENSION,
                "pooling": "mean",
                "normalized": True,
                "document_prefix": "passage: ",
                "query_prefix": "query: ",
            },
            "bm25": {
                "repo_id": BM25_SNAPSHOT.repo_id,
                "revision": BM25_SNAPSHOT.revision,
                "k": 1.2,
                "b": 0.75,
                "avg_len": 256.0,
                "language": "english",
                "token_max_length": 40,
                "disable_stemmer": False,
            },
        },
        "dependencies": dependency_versions,
        "uv_lock_sha256": sha256_file(Path(__file__).parents[3] / "uv.lock"),
        "source_sha256": _source_digest(),
    }


def _rank_items(
    *,
    point_scores: dict[str, float],
    corpus_ids: Sequence[str],
    missing_score: float,
    limit: int,
) -> list[dict[str, Any]]:
    if not math.isfinite(missing_score) or any(
        not math.isfinite(score) for score in point_scores.values()
    ):
        raise RuntimeError("retrieval scores must be finite")
    corpus_order = {memory_id: index for index, memory_id in enumerate(corpus_ids)}
    ranked_ids = sorted(
        corpus_ids,
        key=lambda memory_id: (
            -point_scores.get(memory_id, missing_score),
            corpus_order[memory_id],
        ),
    )[:limit]
    return [
        {
            "id": memory_id,
            "score": point_scores.get(memory_id, missing_score),
        }
        for memory_id in ranked_ids
    ]


def reciprocal_rank_fusion(
    *rankings: Sequence[dict[str, Any]],
    limit: int,
    rank_constant: int = RRF_RANK_CONSTANT,
) -> list[dict[str, Any]]:
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    next_order = 0
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            item_id = item["id"]
            if item_id not in first_seen:
                first_seen[item_id] = next_order
                next_order += 1
            scores[item_id] = scores.get(item_id, 0.0) + 1 / (rank_constant + rank)
    ranked_ids = sorted(
        scores, key=lambda item_id: (-scores[item_id], first_seen[item_id])
    )
    return [{"id": item_id, "score": scores[item_id]} for item_id in ranked_ids[:limit]]


def _retrieve_case(
    *,
    dense_encoder: FastEmbedE5Encoder,
    bm25_encoder: FastEmbedBM25Encoder,
    case: dict[str, Any],
    corpus: Sequence[dict[str, Any]],
    candidate_count: int,
    e5_batch_size: int,
) -> dict[str, Any]:
    client = QdrantClient(":memory:")
    store = QdrantStore(
        client=client,
        collection_name="longmemeval_case",
        dimension=MULTILINGUAL_E5_BASE_DIMENSION,
        bm25_encoder=bm25_encoder,
    )
    memory_id_to_session_id = {
        memory["id"]: memory["source_session_id"] for memory in corpus
    }
    corpus_session_ids = [memory["source_session_id"] for memory in corpus]
    if not corpus:
        raise RuntimeError(f"{case['id']}: LongMemEval corpus is empty")
    if len(set(corpus_session_ids)) != len(corpus_session_ids):
        raise RuntimeError(f"{case['id']}: LongMemEval session ids are not unique")
    if len(memory_id_to_session_id) != len(corpus):
        raise RuntimeError(f"{case['id']}: LongMemEval memory ids are not unique")

    try:
        dense_vectors = dense_encoder.encode_documents(
            (memory["text"] for memory in corpus),
            batch_size=e5_batch_size,
        )
        sparse_vectors = bm25_encoder.encode_documents(
            (memory["text"] for memory in corpus),
            batch_size=max(e5_batch_size, 32),
        )
        if len(dense_vectors) != len(corpus) or len(sparse_vectors) != len(corpus):
            raise RuntimeError("encoder output count does not match LongMemEval corpus")

        points = [
            models.PointStruct(
                id=memory["id"],
                vector={"": dense_vector, "bm25": sparse_vector},
                payload={
                    "data": memory["text"],
                    "source_session_id": memory["source_session_id"],
                },
            )
            for memory, dense_vector, sparse_vector in zip(
                corpus,
                dense_vectors,
                sparse_vectors,
                strict=True,
            )
        ]
        client.upsert(
            collection_name=store.collection_name,
            points=points,
            wait=True,
        )

        dense_query = dense_encoder.encode_query(case["query"])
        sparse_query = bm25_encoder.encode_query(case["query"])
        dense_response = client.query_points(
            collection_name=store.collection_name,
            query=dense_query,
            limit=len(corpus),
        )
        if len(sparse_query.indices) > 0:
            sparse_response = client.query_points(
                collection_name=store.collection_name,
                query=sparse_query,
                using="bm25",
                limit=len(corpus),
            )
            sparse_points = sparse_response.points
        else:
            sparse_points = []

        dense_scores = {
            memory_id_to_session_id[str(point.id)]: float(point.score)
            for point in dense_response.points
        }
        sparse_scores = {
            memory_id_to_session_id[str(point.id)]: float(point.score)
            for point in sparse_points
        }
        if set(dense_scores) != set(corpus_session_ids):
            missing_ids = set(corpus_session_ids).difference(dense_scores)
            unexpected_ids = set(dense_scores).difference(corpus_session_ids)
            raise RuntimeError(
                f"{case['id']}: dense retrieval did not return the complete corpus; "
                f"missing={sorted(missing_ids)}, unexpected={sorted(unexpected_ids)}"
            )
        e5_ranking = _rank_items(
            point_scores=dense_scores,
            corpus_ids=corpus_session_ids,
            missing_score=0.0,
            limit=candidate_count,
        )
        bm25_ranking = _rank_items(
            point_scores=sparse_scores,
            corpus_ids=corpus_session_ids,
            missing_score=0.0,
            limit=candidate_count,
        )
        rrf_ranking = reciprocal_rank_fusion(
            e5_ranking,
            bm25_ranking,
            limit=candidate_count,
        )
    finally:
        store.close()

    return {
        "schema": CANDIDATE_STAGE_SCHEMA,
        "case_id": case["id"],
        "question_type": next(
            tag for tag in case["tags"] if tag not in {"longmemeval", "single", "multi"}
        ),
        "query": case["query"],
        "relevant_ids": case["relevant_session_ids"],
        "corpus_ids": corpus_session_ids,
        "rankings": {
            "e5": e5_ranking,
            "bm25": bm25_ranking,
            "rrf": rrf_ranking,
        },
    }


def run_candidate_stage(
    *,
    dataset: dict[str, Any],
    dataset_path: Path,
    cache_root: Path,
    run_dir: Path,
    fastembed_cache: Path,
    candidate_count: int,
    e5_batch_size: int,
    local_files_only: bool,
) -> dict[str, Any]:
    dependency_versions = require_cuda_candidate_environment()
    runtime = inspect_cuda_runtime()
    question_ids = [case["id"] for case in dataset["queries"]]
    identity = build_candidate_identity(
        dataset_path=dataset_path,
        question_ids=question_ids,
        candidate_count=candidate_count,
        e5_batch_size=e5_batch_size,
        dependency_versions={
            **dependency_versions,
            "qdrant-client": metadata.version("qdrant-client"),
            "jieba": metadata.version("jieba"),
        },
    )
    cache_key = canonical_digest(identity)
    cache_dir = cache_root / cache_key
    records_path = cache_dir / "candidates.jsonl"
    cache_manifest_path = cache_dir / "manifest.json"
    run_manifest_path = run_dir / "candidate-stage.json"
    cache_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    record_by_id = read_resumable_jsonl(records_path)
    unexpected_ids = set(record_by_id).difference(question_ids)
    if unexpected_ids:
        raise RuntimeError(
            f"candidate cache contains unexpected cases: {unexpected_ids}"
        )

    started_at = utc_now()
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
        e5_path = resolve_snapshot(
            E5_SNAPSHOT,
            cache_dir=fastembed_cache,
            local_files_only=local_files_only,
        )
        bm25_path = resolve_snapshot(
            BM25_SNAPSHOT,
            cache_dir=fastembed_cache,
            local_files_only=local_files_only,
        )
        jieba.setLogLevel(logging.WARNING)
        dense_encoder = build_multilingual_e5_base_encoder(
            cache_dir=fastembed_cache,
            model_path=e5_path,
            require_cuda=True,
            device_id=0,
        )
        if not _has_verified_e5_cuda_execution(dense_encoder.cuda_execution):
            raise RuntimeError(
                f"E5 CUDA execution assertion failed: {dense_encoder.cuda_execution}"
            )
        runtime["e5_cuda_execution"] = dense_encoder.cuda_execution
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
        bm25_encoder = FastEmbedBM25Encoder(
            model=SparseTextEmbedding(
                model_name=BM25_SNAPSHOT.repo_id,
                cache_dir=str(fastembed_cache),
                specific_model_path=str(bm25_path),
                k=1.2,
                b=0.75,
                avg_len=256.0,
                language="english",
                token_max_length=40,
                disable_stemmer=False,
            ),
            chinese_segmenter=jieba.cut,
        )

        memory_by_space: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for memory in dataset["memories"]:
            memory_by_space[memory["space_id"]].append(memory)

        with records_path.open("a", encoding="utf-8") as output:
            for case in tqdm(
                dataset["queries"],
                desc="E5 + BM25 + RRF",
                unit="case",
                dynamic_ncols=True,
            ):
                if case["id"] in record_by_id:
                    continue
                corpus = memory_by_space[case["context"]["space_id"]]
                record = _retrieve_case(
                    dense_encoder=dense_encoder,
                    bm25_encoder=bm25_encoder,
                    case=case,
                    corpus=corpus,
                    candidate_count=candidate_count,
                    e5_batch_size=e5_batch_size,
                )
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
                record_by_id[case["id"]] = record
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

    if not _has_verified_e5_cuda_execution(runtime.get("e5_cuda_execution")):
        raise RuntimeError("candidate cache lacks verified E5 CUDA runtime evidence")
    ordered_records = [record_by_id[question_id] for question_id in question_ids]
    rewrite_jsonl(records_path, ordered_records)
    finished_at = utc_now()
    manifest = {
        "status": "complete",
        "cache_key": cache_key,
        "identity": identity,
        "runtime": runtime,
        "started_at": started_at,
        "finished_at": finished_at,
        "record_count": len(ordered_records),
        "dataset_stats": dataset["stats"],
        "excluded_cases": dataset["excluded_cases"],
        "artifact_path": str(records_path.resolve()),
    }
    atomic_write_json(cache_manifest_path, manifest)
    atomic_write_json(run_manifest_path, manifest)
    return manifest


def load_candidate_records(
    manifest_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        raise RuntimeError(f"candidate stage is not complete: {manifest_path}")
    records_path = Path(manifest["artifact_path"])
    record_by_id = read_resumable_jsonl(records_path)
    expected_count = manifest.get("record_count")
    if len(record_by_id) != expected_count:
        raise RuntimeError(
            f"candidate record count mismatch: {len(record_by_id)} != {expected_count}"
        )
    question_ids = manifest["identity"]["dataset"]["question_ids"]
    return manifest, [record_by_id[question_id] for question_id in question_ids]
