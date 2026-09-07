from __future__ import annotations

import platform
import subprocess
import sys
from typing import Any

EXPECTED_GPU_NAME = "NVIDIA GeForce RTX 2070 SUPER"
EXPECTED_DRIVER_VERSION = "550.142"
EXPECTED_GPU_MEMORY_MIB = 8192
EXPECTED_TORCH_VERSION = "2.6.0+cu124"
EXPECTED_TORCH_CUDA = "12.4"


def _parse_nvidia_profile(output: str) -> tuple[str, str, int]:
    gpu_rows = [line.strip() for line in output.splitlines() if line.strip()]
    if len(gpu_rows) != 1:
        raise RuntimeError(f"expected exactly one NVIDIA GPU, found {gpu_rows}")
    fields = [field.strip() for field in gpu_rows[0].split(",")]
    if len(fields) != 3:
        raise RuntimeError(f"unexpected nvidia-smi output: {gpu_rows[0]}")
    gpu_name, driver_version, memory_mib_text = fields
    try:
        memory_mib = int(memory_mib_text)
    except ValueError as exc:
        raise RuntimeError(
            f"unexpected NVIDIA memory value: {memory_mib_text}"
        ) from exc
    return gpu_name, driver_version, memory_mib


def require_pinned_cuda_host() -> dict[str, Any]:
    """Validate and describe the one host allowed to produce the formal baseline."""
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError(
            f"CUDA evaluation requires Python 3.13, found {platform.python_version()}"
        )
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise RuntimeError("CUDA evaluation requires Linux x86_64")
    try:
        os_release = platform.freedesktop_os_release()
    except OSError as exc:
        raise RuntimeError("could not inspect the Linux distribution") from exc
    if os_release.get("ID") != "ubuntu" or os_release.get("VERSION_ID") != "20.04":
        raise RuntimeError(
            "CUDA evaluation requires Ubuntu 20.04, found "
            f"{os_release.get('ID')} {os_release.get('VERSION_ID')}"
        )

    try:
        query = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("nvidia-smi host inspection failed") from exc
    gpu_name, driver_version, memory_mib = _parse_nvidia_profile(query.stdout)
    expected_profile = (
        EXPECTED_GPU_NAME,
        EXPECTED_DRIVER_VERSION,
        EXPECTED_GPU_MEMORY_MIB,
    )
    actual_profile = (gpu_name, driver_version, memory_mib)
    if actual_profile != expected_profile:
        raise RuntimeError(
            f"CUDA host profile changed: expected={expected_profile}, "
            f"actual={actual_profile}"
        )

    import torch

    if torch.__version__ != EXPECTED_TORCH_VERSION:
        raise RuntimeError(
            f"expected torch {EXPECTED_TORCH_VERSION}, found {torch.__version__}"
        )
    if torch.version.cuda != EXPECTED_TORCH_CUDA:
        raise RuntimeError(
            f"expected PyTorch CUDA {EXPECTED_TORCH_CUDA}, found {torch.version.cuda}"
        )
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("the pinned CUDA device is unavailable")
    torch.cuda.set_device(0)
    torch.empty(1, device="cuda:0")
    if torch.cuda.get_device_name(0) != EXPECTED_GPU_NAME:
        raise RuntimeError(
            f"PyTorch resolved an unexpected GPU: {torch.cuda.get_device_name(0)}"
        )
    return {
        "os": "ubuntu-20.04",
        "architecture": "x86_64",
        "python": platform.python_version(),
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "cuda_device": gpu_name,
        "cuda_capability": list(torch.cuda.get_device_capability(0)),
        "gpu_memory_mib": memory_mib,
        "nvidia_driver": driver_version,
    }
