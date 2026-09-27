"""Pre-render per-kill assets that need heavy models (SAM cut-outs) and attach them to the script."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2

from src.ai.schema import MontageScript
from src.config.models import GhostFreezeEffectConfig
from src.detection.enemy_cutout import CutoutError, enemy_cutout_at_kill, load_sam

log = logging.getLogger(__name__)

MAX_GHOSTS = 3


def _candidate_order(script: MontageScript) -> list[int]:
    idx = [i for i, c in enumerate(script.clips) if c.ghost_candidate]
    return sorted(idx, key=lambda i: (script.clips[i].recipe == "cinematic", script.clips[i].score), reverse=True)


def attach_ghost_cutouts(
    script: MontageScript,
    *,
    video_paths: list[Path],
    out_dir: Path,
    resolution: tuple[int, int],
    sam_model_path: Path,
    max_ghosts: int = MAX_GHOSTS,
) -> MontageScript:
    """Enable ghost_freeze on up to ``max_ghosts`` candidates whose SAM mask validates."""
    order = _candidate_order(script)
    if not order:
        return script
    try:
        model = load_sam(sam_model_path)
    except CutoutError:
        log.exception("kill_assets: SAM unavailable; montage renders without ghost freeze-frames")
        return script
    ghost_dir = out_dir / "ghosts"
    ghost_dir.mkdir(parents=True, exist_ok=True)
    clips = list(script.clips)
    attached = 0
    for i in order:
        if attached >= max_ghosts:
            break
        c = clips[i]
        cut = enemy_cutout_at_kill(model, video_paths[c.video_index], float(c.kill_timestamp_sec), resolution)
        if cut is None:
            log.info("kill_assets: clip %d kill %.2fs has no clean enemy mask; skipped", i, c.kill_timestamp_sec)
            continue
        path = ghost_dir / f"clip_{i:02d}.png"
        cv2.imwrite(str(path), cv2.cvtColor(cut.rgba, cv2.COLOR_RGBA2BGRA))
        ghost = GhostFreezeEffectConfig(enabled=True, cutout_path=str(path), anchor_x=cut.x, anchor_y=cut.y)
        clips[i] = c.model_copy(update={"effects": c.effects.model_copy(update={"ghost_freeze": ghost})})
        attached += 1
    log.info("kill_assets: ghost freeze-frames attached to %d/%d candidates", attached, len(order))
    del model
    try:
        import torch

        torch.cuda.empty_cache()
    except ImportError:
        pass
    return script.model_copy(update={"clips": clips})
