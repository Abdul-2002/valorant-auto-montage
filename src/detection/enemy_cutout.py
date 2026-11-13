"""Enemy cut-out at the kill frame via SAM 2 prompts near the crosshair.

On a kill the enemy is normally under the crosshair (screen center). A single
center point is brittle; we try a small multi-point cluster + a tight center
box, then reject masks that fail size / position / compactness checks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.cv.mask_refine import cleanup_mask

log = logging.getLogger(__name__)

MASK_AREA_RANGE = (0.0015, 0.12)
MAX_CENTROID_DIST_FRAC = 0.14  # of frame height
# Sample earlier so the enemy is still standing (post-death floor grabs fail).
SAMPLE_OFFSETS_SEC = (0.08, 0.16, 0.28)
_PAD_PX = 12
# Fractional offsets from center for multi-point prompts (positive labels).
_CROSSHAIR_POINT_OFFSETS = (
    (0.0, 0.0),
    (0.012, 0.0),
    (-0.012, 0.0),
    (0.0, 0.018),
    (0.0, -0.018),
)
# Half-width/height of the center prompt box (tighter than the old 0.08).
_CENTER_BOX_FRAC = 0.05
# Reject if morph+CC drops more than this fraction of the raw mask (speckles).
_MIN_KEEP_FRAC = 0.65
# Reject elongated ground strips (bbox long/short).
_MAX_BBOX_ASPECT = 2.2


class CutoutError(RuntimeError):
    """SAM could not be loaded or run."""


@dataclass(frozen=True)
class Cutout:
    rgba: np.ndarray  # cropped RGBA sprite
    x: int  # top-left in frame pixels
    y: int


def load_sam(model_path: Path):
    try:
        from ultralytics import SAM
    except ImportError as exc:
        raise CutoutError("ultralytics is required for SAM cut-outs") from exc
    model = SAM(str(model_path))
    model(np.zeros((64, 64, 3), np.uint8), points=[[32, 32]], labels=[1], verbose=False)
    return model


def _bbox_aspect(mask: np.ndarray) -> float:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return 0.0
    bw = float(xs.max() - xs.min() + 1)
    bh = float(ys.max() - ys.min() + 1)
    short = max(1.0, min(bw, bh))
    return max(bw, bh) / short


def _valid(mask: np.ndarray) -> bool:
    h, w = mask.shape
    area = float(mask.mean())
    if not MASK_AREA_RANGE[0] <= area <= MASK_AREA_RANGE[1]:
        return False
    if mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any():
        return False
    if _bbox_aspect(mask) > _MAX_BBOX_ASPECT:
        return False
    ys, xs = np.nonzero(mask)
    return float(np.hypot(xs.mean() - w / 2, ys.mean() - h / 2)) <= MAX_CENTROID_DIST_FRAC * h


def refine_enemy_mask(mask: np.ndarray) -> np.ndarray | None:
    """Cleanup SAM output and reject speckly / elongated / off-center masks."""
    raw = np.asarray(mask).astype(bool)
    if not raw.any():
        return None
    cleaned = cleanup_mask(raw)
    if not cleaned.any():
        return None
    keep = float(cleaned.sum()) / float(raw.sum())
    if keep < _MIN_KEEP_FRAC:
        return None
    if not _valid(cleaned):
        return None
    return cleaned


def _pick_best_mask(
    masks: np.ndarray,
    scores: np.ndarray | None,
) -> np.ndarray | None:
    if masks.size == 0:
        return None
    conf = scores if scores is not None and len(scores) == len(masks) else np.ones(len(masks))
    refined: list[tuple[int, np.ndarray]] = []
    for i in range(len(masks)):
        out = refine_enemy_mask(masks[i])
        if out is not None:
            refined.append((i, out))
    if not refined:
        return None
    _best_i, best_mask = max(refined, key=lambda pair: float(conf[pair[0]]))
    return best_mask


def _run_point_prompt(model, bgr: np.ndarray, points: list[list[int]]) -> np.ndarray | None:
    labels = [1] * len(points)
    res = model.predictor(bgr, points=points, labels=labels, multimask_output=True)
    if not res or res[0].masks is None:
        return None
    masks = res[0].masks.data.cpu().numpy().astype(bool)
    scores = res[0].boxes.conf.cpu().numpy() if res[0].boxes is not None else None
    return _pick_best_mask(masks, scores)


def _run_box_prompt(model, bgr: np.ndarray, box: list[int]) -> np.ndarray | None:
    res = model.predictor(bgr, bboxes=[box], multimask_output=True)
    if not res or res[0].masks is None:
        return None
    masks = res[0].masks.data.cpu().numpy().astype(bool)
    scores = res[0].boxes.conf.cpu().numpy() if res[0].boxes is not None else None
    return _pick_best_mask(masks, scores)


def best_enemy_mask(model, frame_rgb: np.ndarray) -> np.ndarray | None:
    """Best valid SAM mask near crosshair using multi-point then center-box prompts."""
    h, w = frame_rgb.shape[:2]
    bgr = np.ascontiguousarray(frame_rgb[:, :, ::-1])
    cx, cy = w // 2, h // 2
    points = [
        [int(cx + dx * w), int(cy + dy * h)]
        for dx, dy in _CROSSHAIR_POINT_OFFSETS
    ]
    mask = _run_point_prompt(model, bgr, points)
    if mask is not None:
        return mask
    half_w = max(8, int(_CENTER_BOX_FRAC * w))
    half_h = max(8, int(_CENTER_BOX_FRAC * h))
    box = [cx - half_w, cy - half_h, cx + half_w, cy + half_h]
    return _run_box_prompt(model, bgr, box)


def to_cutout(frame_rgb: np.ndarray, mask: np.ndarray, *, feather_radius_px: float = 4.0) -> Cutout:
    from src.cv.mask_refine import feather_mask_alpha

    ys, xs = np.nonzero(mask)
    h, w = mask.shape
    x0, y0 = max(0, xs.min() - _PAD_PX), max(0, ys.min() - _PAD_PX)
    x1, y1 = min(w, xs.max() + _PAD_PX + 1), min(h, ys.max() + _PAD_PX + 1)
    # Distance-transform feather (not a thin Gaussian on a hard bit mask) kills
    # stair-step edges on ghost cut-outs under motion blur / scale.
    alpha = feather_mask_alpha(mask[y0:y1, x0:x1], radius_px=float(feather_radius_px))
    rgba = np.dstack([frame_rgb[y0:y1, x0:x1], (alpha * 255.0).astype(np.uint8)])
    return Cutout(rgba=rgba, x=int(x0), y=int(y0))


def read_frame_rgb(video_path: Path, t_sec: float, size: tuple[int, int]) -> np.ndarray | None:
    from src.io.nv_decode import read_rgb_frame_at

    return read_rgb_frame_at(Path(video_path), t_sec=float(t_sec), size=size)


def enemy_cutout_at_kill(model, video_path: Path, kill_sec: float, size: tuple[int, int]) -> Cutout | None:
    for offset in SAMPLE_OFFSETS_SEC:
        frame = read_frame_rgb(video_path, kill_sec - offset, size)
        if frame is None:
            continue
        mask = best_enemy_mask(model, frame)
        if mask is not None:
            return to_cutout(frame, mask)
    return None
