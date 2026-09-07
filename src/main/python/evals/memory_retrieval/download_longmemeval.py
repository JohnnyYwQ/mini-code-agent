from __future__ import annotations

import argparse
import hashlib
import tempfile
import urllib.request
from pathlib import Path

REVISION = "98d7416c24c778c2fee6e6f3006e7a073259d48f"
FILE_NAME = "longmemeval_s_cleaned.json"
DOWNLOAD_URL = (
    "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/"
    f"resolve/{REVISION}/{FILE_NAME}"
)
EXPECTED_SIZE = 277_383_467
EXPECTED_SHA256 = "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "data" / FILE_NAME
CHUNK_SIZE = 1024 * 1024
PROGRESS_INTERVAL = 25 * 1024 * 1024


def _verify(path: Path) -> None:
    size = path.stat().st_size
    if size != EXPECTED_SIZE:
        raise RuntimeError(
            f"unexpected file size for {path}: {size}, expected {EXPECTED_SIZE}"
        )

    digest = hashlib.sha256()
    with path.open("rb") as dataset_file:
        while chunk := dataset_file.read(CHUNK_SIZE):
            digest.update(chunk)
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != EXPECTED_SHA256:
        raise RuntimeError(
            f"unexpected SHA-256 for {path}: {actual_sha256}, "
            f"expected {EXPECTED_SHA256}"
        )


def download(*, output: Path) -> None:
    if output.exists():
        _verify(output)
        print(f"Verified existing dataset: {output}")
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    digest = hashlib.sha256()
    downloaded = 0
    next_progress = PROGRESS_INTERVAL

    try:
        request = urllib.request.Request(
            DOWNLOAD_URL,
            headers={"User-Agent": "mini-code-agent-memory-eval/0.2"},
        )
        with (
            urllib.request.urlopen(request, timeout=60) as response,
            tempfile.NamedTemporaryFile(
                dir=output.parent,
                prefix=f".{FILE_NAME}.",
                suffix=".part",
                delete=False,
            ) as temporary_file,
        ):
            temporary_path = Path(temporary_file.name)
            while chunk := response.read(CHUNK_SIZE):
                temporary_file.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                if downloaded >= next_progress:
                    print(
                        f"Downloaded {downloaded / 1024 / 1024:.0f} MiB...", flush=True
                    )
                    next_progress += PROGRESS_INTERVAL

        if downloaded != EXPECTED_SIZE:
            raise RuntimeError(
                f"unexpected download size: {downloaded}, expected {EXPECTED_SIZE}"
            )
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != EXPECTED_SHA256:
            raise RuntimeError(
                f"unexpected download SHA-256: {actual_sha256}, "
                f"expected {EXPECTED_SHA256}"
            )

        temporary_path.replace(output)
        print(f"Downloaded and verified dataset: {output}")
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download the pinned LongMemEval-S retrieval dataset"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"dataset path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()
    download(output=args.output)


if __name__ == "__main__":
    main()
