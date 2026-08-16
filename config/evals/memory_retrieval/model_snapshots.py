from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import snapshot_download


@dataclass(frozen=True, slots=True)
class ModelSnapshot:
    repo_id: str
    revision: str
    required_patterns: tuple[str, ...]
    allow_patterns: tuple[str, ...] | None = None

    def expected_path(self, cache_dir: str | Path) -> Path:
        repository_dir = f"models--{self.repo_id.replace('/', '--')}"
        return Path(cache_dir) / repository_dir / "snapshots" / self.revision

    def validate(self, path: str | Path) -> Path:
        snapshot_path = Path(path)
        missing = [
            pattern
            for pattern in self.required_patterns
            if not any(snapshot_path.glob(pattern))
        ]
        if missing:
            raise RuntimeError(
                f"incomplete model snapshot {self.repo_id}@{self.revision}: "
                f"missing {missing} under {snapshot_path}"
            )
        return snapshot_path


E5_SNAPSHOT = ModelSnapshot(
    repo_id="intfloat/multilingual-e5-base",
    revision="d128750597153bb5987e10b1c3493a34e5a4502a",
    required_patterns=("config.json", "tokenizer.json", "onnx/model.onnx"),
    allow_patterns=(
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "onnx/model.onnx",
    ),
)

BM25_SNAPSHOT = ModelSnapshot(
    repo_id="Qdrant/bm25",
    revision="e499a1f8d6bec960aab5533a0941bf914e70faf9",
    required_patterns=("config.json", "english.txt"),
    allow_patterns=("config.json", "*.txt"),
)

BGE_SNAPSHOT = ModelSnapshot(
    repo_id="BAAI/bge-reranker-v2-m3",
    revision="953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
    required_patterns=("config.json", "tokenizer*.json", "*.safetensors"),
)


def resolve_snapshot(
    snapshot: ModelSnapshot,
    *,
    cache_dir: str | Path,
    local_files_only: bool,
) -> Path:
    """Resolve one exact Hugging Face commit and reject incomplete caches."""
    expected_path = snapshot.expected_path(cache_dir)
    try:
        return snapshot.validate(expected_path)
    except RuntimeError:
        pass

    resolved = snapshot_download(
        repo_id=snapshot.repo_id,
        revision=snapshot.revision,
        cache_dir=str(cache_dir),
        allow_patterns=snapshot.allow_patterns,
        local_files_only=local_files_only,
    )
    resolved_path = Path(resolved)
    if resolved_path.name != snapshot.revision:
        raise RuntimeError(
            f"resolved unexpected revision for {snapshot.repo_id}: {resolved_path}"
        )
    return snapshot.validate(resolved_path)
