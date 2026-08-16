#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly PYTHON_VERSION="3.13"
readonly ENV_DIR="${MINI_CODE_AGENT_ENV_DIR:-${HOME}/.local/share/mini-code-agent/venvs/cu124}"
readonly PYTHON_BIN="${ENV_DIR}/bin/python"
readonly EVAL_HOME="${MINI_CODE_AGENT_EVAL_HOME:-${HOME}/.local/share/mini-code-agent/eval}"
readonly CACHE_ROOT="${EVAL_HOME}/cache"
readonly RUN_ROOT="${EVAL_HOME}/runs"
readonly RUN_ID="${MINI_CODE_AGENT_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
readonly RUN_DIR="${RUN_ROOT}/${RUN_ID}"
readonly SMOKE_DIR="${RUN_DIR}/smoke"
readonly FULL_DIR="${RUN_DIR}/full"
readonly PROXY_URL="${MINI_CODE_AGENT_PROXY_URL:-}"
readonly MINIMUM_FREE_BYTES=$((40 * 1024 * 1024 * 1024))
readonly DATASET_SHA256="d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
readonly E5_REVISION="d128750597153bb5987e10b1c3493a34e5a4502a"
readonly BM25_REVISION="e499a1f8d6bec960aab5533a0941bf914e70faf9"
readonly BGE_REVISION="953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"

fail() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

find_uv() {
    local candidate
    candidate="$(command -v uv || true)"
    if [[ -z "${candidate}" && -x "${HOME}/.local/bin/uv" ]]; then
        candidate="${HOME}/.local/bin/uv"
    fi
    [[ -n "${candidate}" ]] || fail "uv is not installed or not on PATH"
    printf '%s\n' "${candidate}"
}

choose_dataset_path() {
    local repository_dataset
    repository_dataset="${REPO_ROOT}/config/evals/memory_retrieval/data/longmemeval_s_cleaned.json"
    if [[ -n "${MINI_CODE_AGENT_DATASET_PATH:-}" ]]; then
        printf '%s\n' "${MINI_CODE_AGENT_DATASET_PATH}"
    elif [[ -f "${repository_dataset}" ]]; then
        printf '%s\n' "${repository_dataset}"
    else
        printf '%s\n' "${EVAL_HOME}/data/longmemeval_s_cleaned.json"
    fi
}

choose_fastembed_cache() {
    local legacy_cache
    legacy_cache="/tmp/fastembed_cache"
    if [[ -n "${MINI_CODE_AGENT_FASTEMBED_CACHE:-}" ]]; then
        printf '%s\n' "${MINI_CODE_AGENT_FASTEMBED_CACHE}"
    elif [[ -f "${legacy_cache}/models--intfloat--multilingual-e5-base/snapshots/${E5_REVISION}/onnx/model.onnx" \
        && -f "${legacy_cache}/models--Qdrant--bm25/snapshots/${BM25_REVISION}/config.json" ]]; then
        printf '%s\n' "${legacy_cache}"
    else
        printf '%s\n' "${EVAL_HOME}/models/fastembed"
    fi
}

choose_huggingface_cache() {
    local legacy_cache
    legacy_cache="${HOME}/.cache/huggingface/hub"
    if [[ -n "${MINI_CODE_AGENT_HF_CACHE:-}" ]]; then
        printf '%s\n' "${MINI_CODE_AGENT_HF_CACHE}"
    elif [[ -f "${legacy_cache}/models--BAAI--bge-reranker-v2-m3/snapshots/${BGE_REVISION}/config.json" ]]; then
        printf '%s\n' "${legacy_cache}"
    else
        printf '%s\n' "${EVAL_HOME}/models/huggingface/hub"
    fi
}

model_snapshot_complete() {
    local stage="$1"
    if [[ "${stage}" == "candidate" ]]; then
        [[ -f "${FASTEMBED_CACHE}/models--intfloat--multilingual-e5-base/snapshots/${E5_REVISION}/config.json" \
            && -f "${FASTEMBED_CACHE}/models--intfloat--multilingual-e5-base/snapshots/${E5_REVISION}/tokenizer.json" \
            && -f "${FASTEMBED_CACHE}/models--intfloat--multilingual-e5-base/snapshots/${E5_REVISION}/onnx/model.onnx" \
            && -f "${FASTEMBED_CACHE}/models--Qdrant--bm25/snapshots/${BM25_REVISION}/config.json" \
            && -f "${FASTEMBED_CACHE}/models--Qdrant--bm25/snapshots/${BM25_REVISION}/english.txt" ]]
    else
        compgen -G "${HUGGINGFACE_CACHE}/models--BAAI--bge-reranker-v2-m3/snapshots/${BGE_REVISION}/*.safetensors" >/dev/null \
            && compgen -G "${HUGGINGFACE_CACHE}/models--BAAI--bge-reranker-v2-m3/snapshots/${BGE_REVISION}/tokenizer*.json" >/dev/null \
            && [[ -f "${HUGGINGFACE_CACHE}/models--BAAI--bge-reranker-v2-m3/snapshots/${BGE_REVISION}/config.json" ]]
    fi
}

readonly UV_BIN="$(find_uv)"
readonly DATASET_PATH="$(choose_dataset_path)"
readonly FASTEMBED_CACHE="$(choose_fastembed_cache)"
readonly HUGGINGFACE_CACHE="$(choose_huggingface_cache)"

[[ "$(uname -m)" == "x86_64" ]] || fail "the pinned CUDA host must be x86_64"
[[ -r /etc/os-release ]] || fail "/etc/os-release is unavailable"
# shellcheck disable=SC1091
. /etc/os-release
[[ "${ID}" == "ubuntu" && "${VERSION_ID}" == "20.04" ]] \
    || fail "the pinned CUDA host must run Ubuntu 20.04"
command -v nvidia-smi >/dev/null 2>&1 || fail "nvidia-smi is unavailable"
command -v git >/dev/null 2>&1 || fail "git is unavailable"
command -v flock >/dev/null 2>&1 || fail "flock is unavailable"
[[ -f "${REPO_ROOT}/pyproject.toml" && -f "${REPO_ROOT}/uv.lock" ]] \
    || fail "run this script from a complete mini-code-agent checkout"

repo_status="$(git -C "${REPO_ROOT}" status --porcelain=v1 --untracked-files=all)"
if [[ -n "${repo_status}" && "${MINI_CODE_AGENT_ALLOW_DIRTY:-0}" != "1" ]]; then
    printf '%s\n' "${repo_status}" >&2
    fail "the worktree is dirty; commit it for a formal baseline or set MINI_CODE_AGENT_ALLOW_DIRTY=1 for a provisional run"
fi

if [[ -n "${PROXY_URL}" ]]; then
    export HTTP_PROXY="${PROXY_URL}"
    export HTTPS_PROXY="${PROXY_URL}"
    export http_proxy="${PROXY_URL}"
    export https_proxy="${PROXY_URL}"
    export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1}"
    export no_proxy="${no_proxy:-localhost,127.0.0.1}"
    printf 'Download proxy: enabled\n'
else
    printf 'Download proxy: not configured\n'
fi

export UV_NO_PROGRESS=1
export TOKENIZERS_PARALLELISM=false
export HF_HUB_DISABLE_TELEMETRY=1
export UV_PROJECT_ENVIRONMENT="${ENV_DIR}"

mkdir -p \
    "${EVAL_HOME}" \
    "${CACHE_ROOT}/candidates" \
    "${CACHE_ROOT}/rerank" \
    "${RUN_DIR}" \
    "${FASTEMBED_CACHE}" \
    "${HUGGINGFACE_CACHE}" \
    "$(dirname -- "${DATASET_PATH}")"

exec 9>"${EVAL_HOME}/run.lock"
flock -n 9 || fail "another LongMemEval CUDA run already owns ${EVAL_HOME}/run.lock"

available_bytes="$(df -PB1 "${EVAL_HOME}" | awk 'NR == 2 {print $4}')"
[[ "${available_bytes}" =~ ^[0-9]+$ ]] || fail "could not determine free disk space"
(( available_bytes >= MINIMUM_FREE_BYTES )) \
    || fail "at least 40 GiB of free disk space is required under ${EVAL_HOME}"

printf 'Repository: %s\n' "${REPO_ROOT}"
printf 'Commit: %s\n' "$(git -C "${REPO_ROOT}" rev-parse HEAD)"
printf 'Environment: %s\n' "${ENV_DIR}"
printf 'Evaluation home: %s\n' "${EVAL_HOME}"
printf 'Dataset: %s\n' "${DATASET_PATH}"
printf 'FastEmbed cache: %s\n' "${FASTEMBED_CACHE}"
printf 'Hugging Face cache: %s\n' "${HUGGINGFACE_CACHE}"
printf 'Run directory: %s\n' "${RUN_DIR}"
printf '\nNVIDIA host:\n'
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader

if [[ -x "${PYTHON_BIN}" ]]; then
    current_python_version="$(
        PYTHONDONTWRITEBYTECODE=1 "${PYTHON_BIN}" -c \
            'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
    )"
    [[ "${current_python_version}" == "${PYTHON_VERSION}" ]] \
        || fail "${ENV_DIR} uses Python ${current_python_version}; choose a new MINI_CODE_AGENT_ENV_DIR"
    printf '\nReusing the existing Python %s environment.\n' "${PYTHON_VERSION}"
else
    [[ ! -e "${ENV_DIR}" ]] \
        || fail "${ENV_DIR} exists but has no executable Python; choose a new MINI_CODE_AGENT_ENV_DIR"
    printf '\nCreating the dedicated Python %s environment.\n' "${PYTHON_VERSION}"
    "${UV_BIN}" python install "${PYTHON_VERSION}"
    "${UV_BIN}" venv --python "${PYTHON_VERSION}" "${ENV_DIR}"
fi

cd "${REPO_ROOT}"
sync_arguments=(
    sync
    --frozen
    --no-default-groups
    --extra cuda-eval
    --python "${PYTHON_BIN}"
)
if "${UV_BIN}" "${sync_arguments[@]}" --check >/dev/null 2>&1; then
    printf 'CUDA evaluation dependencies already match uv.lock; no install needed.\n'
else
    printf 'Incrementally synchronizing CUDA evaluation dependencies from uv.lock.\n'
    "${UV_BIN}" "${sync_arguments[@]}"
fi

printf '\nVerifying the CUDA environment selection.\n'
PYTHONPATH="${REPO_ROOT}/config" PYTHONDONTWRITEBYTECODE=1 "${PYTHON_BIN}" - <<'PY'
import importlib.metadata as metadata
import json

from evals.memory_retrieval.cuda_host import require_pinned_cuda_host

expected = {
    "FlagEmbedding": "1.4.0",
    "fastembed-gpu": "0.8.0",
    "onnxruntime-gpu": "1.26.0",
    "torch": "2.6.0+cu124",
    "transformers": "4.57.6",
}
for name, version in expected.items():
    actual = metadata.version(name)
    if actual != version:
        raise SystemExit(f"expected {name}=={version}, found {actual}")
for forbidden in ("fastembed", "onnxruntime"):
    try:
        actual = metadata.version(forbidden)
    except metadata.PackageNotFoundError:
        continue
    raise SystemExit(f"conflicting distribution is installed: {forbidden}=={actual}")

profile = require_pinned_cuda_host()

import onnxruntime as ort

providers = ort.get_available_providers()
if "CUDAExecutionProvider" not in providers:
    raise SystemExit(f"ONNX Runtime CUDA provider is unavailable: {providers}")
print(json.dumps(profile, sort_keys=True))
print(f"onnxruntime={ort.__version__}")
print(f"onnxruntime_providers={providers}")
PY

printf '\nVerifying the pinned LongMemEval-S dataset.\n'
"${PYTHON_BIN}" \
    "${REPO_ROOT}/config/evals/memory_retrieval/download_longmemeval.py" \
    --output "${DATASET_PATH}"
actual_dataset_sha256="$(sha256sum "${DATASET_PATH}" | awk '{print $1}')"
[[ "${actual_dataset_sha256}" == "${DATASET_SHA256}" ]] \
    || fail "LongMemEval-S SHA-256 does not match the pinned dataset"

candidate_model_arguments=()
if model_snapshot_complete candidate; then
    candidate_model_arguments=(--offline)
    printf 'E5/BM25 snapshots: complete; candidate stages will stay offline.\n'
else
    printf 'E5/BM25 snapshots: incomplete; exact pinned files will be downloaded.\n'
fi
rerank_model_arguments=()
if model_snapshot_complete rerank; then
    rerank_model_arguments=(--offline)
    printf 'BGE snapshot: complete; rerank stages will stay offline.\n'
else
    printf 'BGE snapshot: incomplete; the exact pinned revision will be downloaded.\n'
fi

"${UV_BIN}" pip freeze --python "${PYTHON_BIN}" >"${RUN_DIR}/environment.txt"
git -C "${REPO_ROOT}" status --porcelain=v1 --untracked-files=all \
    >"${RUN_DIR}/git-status.txt"

run_candidates() {
    local destination="$1"
    shift
    PYTHONPATH="${REPO_ROOT}/config" PYTHONUNBUFFERED=1 "${PYTHON_BIN}" \
        -m evals.memory_retrieval.run_longmemeval_cuda candidates \
        --dataset "${DATASET_PATH}" \
        --run-dir "${destination}" \
        --cache-root "${CACHE_ROOT}/candidates" \
        --fastembed-cache "${FASTEMBED_CACHE}" \
        "${candidate_model_arguments[@]}" \
        "$@"
}

run_rerank() {
    local destination="$1"
    PYTHONPATH="${REPO_ROOT}/config" PYTHONUNBUFFERED=1 "${PYTHON_BIN}" \
        -m evals.memory_retrieval.run_longmemeval_cuda rerank \
        --dataset "${DATASET_PATH}" \
        --run-dir "${destination}" \
        --cache-root "${CACHE_ROOT}/rerank" \
        --huggingface-cache "${HUGGINGFACE_CACHE}" \
        "${rerank_model_arguments[@]}"
}

printf '\nRunning deterministic CUDA smoke candidates.\n'
run_candidates "${SMOKE_DIR}" --smoke 2>&1 | tee "${RUN_DIR}/smoke-candidates.log"
printf '\nRunning deterministic CUDA smoke BGE reranking.\n'
run_rerank "${SMOKE_DIR}" 2>&1 | tee "${RUN_DIR}/smoke-rerank.log"

printf '\nSmoke passed. Running the full E5/BM25/RRF candidate stage.\n'
run_candidates "${FULL_DIR}" 2>&1 | tee "${RUN_DIR}/full-candidates.log"
printf '\nCandidate stage passed. Running BGE in a fresh process.\n'
run_rerank "${FULL_DIR}" 2>&1 | tee "${RUN_DIR}/full-rerank.log"

printf '\nLongMemEval retrieval baseline complete.\n'
printf 'Baseline: %s\n' "${FULL_DIR}/baseline.json"
printf 'Run artifacts: %s\n' "${RUN_DIR}"
