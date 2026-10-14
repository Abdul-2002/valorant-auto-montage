"""Pre-render weapon contours for the gun_outline effect (multi-frame SAM + cleanup).

Point prompts on the weapon region are unusable; a box over the first-person
weapon region is stable once validated. Bad masks are rejected; survivors are
morphologically cleaned and re-SAM'd at several source offsets so the outline
can track through the post-kill slow-mo (optical-flow fill-in happens at render).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import cv2
import numpy as np

from src.ai.schema import MontageScript
from src.config.models import GunOutlineEffectConfig
from src.detection.enemy_cutout import CutoutError, load_sam, read_frame_rgb

log = logging.getLogger(__name__)

MAX_GUN_OUTLINES = 3
# First-person weapon region (fractions of frame w/h), from the run22 source VODs.
WEAPON_BOX_FRAC = (0.50, 0.58, 0.86, 0.96)
# Clean gun-only masks run ~1-6%; hands+gun land at 7-10%. Above 10% swallows arms/HUD.
AREA_RANGE = (0.01, 0.10)
ASPECT_RANGE = (1.15, 6.0)
MIN_CENTROID_Y_FRAC = 0.55
MIN_CONTOUR_AREA_PX = 40
# Drop island contours smaller than this fraction of the largest component.
ISLAND_MIN_FRAC = 0.12
# Source-time offsets relative to kill for multi-frame SAM (option C).
SAMPLE_OFFSETS_SEC = (-0.05, 0.0, 0.08, 0.16, 0.28)
_MORPH_KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))


def valid_weapon_mask(mask: np.ndarray, area_range: tuple[float, float] = AREA_RANGE) -> bool:
    h, w = mask.shape
    area = float(mask.mean())
    if not area_range[0] <= area <= area_range[1]:
        return False
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return False
    aspect = (xs.max() - xs.min() + 1) / max(ys.max() - ys.min() + 1, 1)
    if not ASPECT_RANGE[0] <= aspect <= ASPECT_RANGE[1]:
        return False
    return float(ys.mean()) >= MIN_CENTROID_Y_FRAC * h


def clean_weapon_mask(mask: np.ndarray, area_range: tuple[float, float] = AREA_RANGE) -> np.ndarray | None:
    """Morph-open + keep the largest connected component in the weapon box."""
    opened = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, _MORPH_KERNEL)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    if n <= 1:
        return None
    # Label 0 is background; pick the largest remaining component.
    areas = stats[1:, cv2.CC_STAT_AREA]
    best = int(np.argmax(areas)) + 1
    cleaned = labels == best
    return cleaned if valid_weapon_mask(cleaned, area_range) else None


def _contours_of(mask: np.ndarray) -> list[np.ndarray]:
    """External contours with tiny HUD islands dropped (option A)."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    kept: list[tuple[float, np.ndarray]] = []
    for c in contours:
        area = float(cv2.contourArea(c))
        if area < MIN_CONTOUR_AREA_PX:
            continue
        approx = cv2.approxPolyDP(c, 2.0, True)
        if len(approx) >= 3:
            kept.append((area, approx))
    if not kept:
        return []
    kept.sort(key=lambda x: x[0], reverse=True)
    largest = kept[0][0]
    # Prefer a single silhouette when satellites are junk fragments.
    primary = [kept[0][1]]
    satellites = [c for a, c in kept[1:] if a >= ISLAND_MIN_FRAC * largest]
    if satellites and sum(cv2.contourArea(c) for c in satellites) >= 0.25 * largest:
        return primary + satellites
    return primary


def weapon_mask_at(
    model,
    video_path: Path,
    src_sec: float,
    size: tuple[int, int],
    area_range: tuple[float, float] = AREA_RANGE,
    multimask: bool = False,
) -> np.ndarray | None:
    """Weapon mask from the box prompt; ``multimask`` keeps the largest valid of SAM's part-to-whole masks."""
    frame = read_frame_rgb(video_path, src_sec, size)
    if frame is None:
        return None
    h, w = frame.shape[:2]
    x0f, y0f, x1f, y1f = WEAPON_BOX_FRAC
    box = [int(x0f * w), int(y0f * h), int(x1f * w), int(y1f * h)]
    bgr = np.ascontiguousarray(frame[:, :, ::-1])
    res = model.predictor(bgr, bboxes=[box], multimask_output=multimask)
    if not res or res[0].masks is None or len(res[0].masks.data) == 0:
        return None
    candidates = sorted((m.astype(bool) for m in res[0].masks.data.cpu().numpy()), key=lambda m: -float(m.mean()))
    for mask in candidates:
        if not valid_weapon_mask(mask, area_range):
            continue
        cleaned = clean_weapon_mask(mask, area_range)
        if cleaned is not None:
            return cleaned
    return None


def weapon_mask_at_kill(model, video_path: Path, kill_sec: float, size: tuple[int, int]) -> np.ndarray | None:
    """Backward-compatible single-frame entry (kill − 0.05s)."""
    return weapon_mask_at(model, video_path, kill_sec - 0.05, size)


def _ser_contours(contours: list[np.ndarray]) -> list[list[list[int]]]:
    return [cnt.reshape(-1, 2).tolist() for cnt in contours]


def _slowmo_factor_of(clip) -> float:
    vel = getattr(clip.effects, "velocity", None)
    if vel is None:
        return 0.45
    return float(getattr(vel, "kill_slowmo_factor", 0.45) or 0.45)


def build_gun_asset(
    model,
    video_path: Path,
    kill_sec: float,
    size: tuple[int, int],
    *,
    slowmo_factor: float,
) -> dict | None:
    """Multi-frame SAM keyframes + cleaned primary contour payload."""
    keyframes: list[dict] = []
    primary: list[np.ndarray] = []
    for offset in SAMPLE_OFFSETS_SEC:
        mask = weapon_mask_at(model, video_path, float(kill_sec) + float(offset), size)
        if mask is None:
            continue
        contours = _contours_of(mask)
        if not contours:
            continue
        keyframes.append({"src_offset": float(offset), "contours": _ser_contours(contours)})
        if abs(offset) < 1e-9 or not primary:
            primary = contours
    if not keyframes:
        return None
    if not primary:
        primary = [
            np.asarray(c, dtype=np.int32).reshape(-1, 1, 2) for c in keyframes[0]["contours"]
        ]
    return {
        "frame": list(size),
        "kill_src_sec": float(kill_sec),
        "slowmo_factor": float(slowmo_factor),
        "contours": _ser_contours(primary),
        "keyframes": keyframes,
    }


def attach_gun_outlines(
    script: MontageScript,
    *,
    video_paths: list[Path],
    out_dir: Path,
    resolution: tuple[int, int],
    sam_model_path: Path,
    max_outlines: int = MAX_GUN_OUTLINES,
) -> MontageScript:
    """Enable gun_outline on up to ``max_outlines`` candidates whose weapon mask validates."""
    order = sorted(
        (i for i, c in enumerate(script.clips) if c.gun_candidate),
        key=lambda i: script.clips[i].score,
        reverse=True,
    )
    if not order:
        return script
    try:
        model = load_sam(sam_model_path)
    except CutoutError:
        log.exception("weapon_assets: SAM unavailable; montage renders without gun outlines")
        return script
    gun_dir = out_dir / "guns"
    gun_dir.mkdir(parents=True, exist_ok=True)
    clips = list(script.clips)
    attached = 0
    for i in order:
        if attached >= max_outlines:
            break
        c = clips[i]
        payload = build_gun_asset(
            model,
            video_paths[c.video_index],
            float(c.kill_timestamp_sec),
            resolution,
            slowmo_factor=_slowmo_factor_of(c),
        )
        if payload is None:
            log.info("weapon_assets: clip %d kill %.2fs has no valid weapon mask; skipped", i, c.kill_timestamp_sec)
            continue
        path = gun_dir / f"clip_{i:02d}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        gun = GunOutlineEffectConfig(enabled=True, asset_path=str(path))
        clips[i] = c.model_copy(update={"effects": c.effects.model_copy(update={"gun_outline": gun})})
        attached += 1
        log.info(
            "weapon_assets: clip %d attached with %d SAM keyframes",
            i,
            len(payload.get("keyframes", [])),
        )
    log.info("weapon_assets: gun outlines attached to %d/%d candidates", attached, len(order))
    del model
    release_gpu_cache()
    return script.model_copy(update={"clips": clips})


def release_gpu_cache() -> None:
    try:
        import torch

        torch.cuda.empty_cache()
    except ImportError:
        pass
