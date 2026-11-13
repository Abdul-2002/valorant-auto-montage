"""Release CUDA memory after heavy jobs so the GPU returns near idle."""

from __future__ import annotations

import gc
import logging

log = logging.getLogger(__name__)


def release_cuda(*, reason: str = "") -> None:
    """Drop cached CUDA allocations held by the worker process."""
    gc.collect()
    try:
        import torch

        if not torch.cuda.is_available():
            return
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        try:
            torch.cuda.ipc_collect()
        except Exception:
            pass
        allocated = torch.cuda.memory_allocated() / (1024**2)
        reserved = torch.cuda.memory_reserved() / (1024**2)
        log.info(
            "gpu_hygiene: released CUDA%s (allocated=%.0fMiB reserved=%.0fMiB)",
            f" after {reason}" if reason else "",
            allocated,
            reserved,
        )
    except ImportError:
        return
