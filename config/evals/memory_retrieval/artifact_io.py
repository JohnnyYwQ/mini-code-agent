from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def rewrite_jsonl(path: Path, records: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    with temporary_path.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n"
            )
    temporary_path.replace(path)


def read_resumable_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    """Read completed case records and discard only a truncated final line."""
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    records: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            if index != len(lines) - 1:
                raise
            rewrite_jsonl(path, records)
            break
        if not isinstance(record, dict):
            raise RuntimeError(f"evaluation artifact record is not an object: {record}")
        records.append(record)

    record_by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        case_id = record.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise RuntimeError(f"evaluation artifact has invalid case id: {record}")
        if case_id in record_by_id:
            raise RuntimeError(f"evaluation artifact repeats case id: {case_id}")
        record_by_id[case_id] = record
    return record_by_id
