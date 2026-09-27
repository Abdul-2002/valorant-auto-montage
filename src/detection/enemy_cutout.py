"""Enemy cut-out at the kill frame via SAM 2 point prompt at the crosshair.

On a kill the enemy is normally under the crosshair (screen center), so a
single positive point is a usable automatic prompt. It fails when the kill
came from an ability or the enemy already dropped; those masks are rejected
by size / position checks rather than shipped as a bad cut-out.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

MASK_AREA_RANGE = (0.0015, 0.12)
MAX_CENTROID_DIST_FRAC = 0.12  # of frame height
SAMPLE_OFFSETS_SEC = (0.03, 0.12)
_PAD_PX = 12


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


def _valid(mask: np.ndarray) -> bool:
    h, w = mask.shape
    area = float(mask.mean())
    if not MASK_AREA_RANGE[0] <= area <= MASK_AREA_RANGE[1]:
        return False
    if mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any():
        return False
    ys, xs = np.nonzero(mask)
    return float(np.hypot(xs.mean() - w / 2, ys.mean() - h / 2)) <= MAX_CENTROID_DIST_FRAC * h


def best_enemy_mask(model, frame_rgb: np.ndarray) -> np.ndarray | None:
    """Highest-scoring valid SAM mask for a point at screen center, or None."""
    h, w = frame_rgb.shape[:2]
    bgr = np.ascontiguousarray(frame_rgb[:, :, ::-1])
    res = model.predictor(bgr, points=[[w // 2, h // 2]], labels=[1], multimask_output=True)
    if not res or res[0].masks is None:
        return None
    masks = res[0].masks.data.cpu().numpy().astype(bool)
    scores = res[0].boxes.conf.cpu().numpy() if res[0].boxes is not None else np.ones(len(masks))
    valid = [i for i in range(len(masks)) if _valid(masks[i])]
    return masks[max(valid, key=lambda i: scores[i])] if valid else None


def to_cutout(frame_rgb: np.ndarray, mask: np.ndarray) -> Cutout:
    ys, xs = np.nonzero(mask)
    h, w = mask.shape
    x0, y0 = max(0, xs.min() - _PAD_PX), max(0, ys.min() - _PAD_PX)
    x1, y1 = min(w, xs.max() + _PAD_PX + 1), min(h, ys.max() + _PAD_PX + 1)
    alpha = cv2.GaussianBlur(mask[y0:y1, x0:x1].astype(np.float32), (0, 0), 1.2)
    rgba = np.dstack([frame_rgb[y0:y1, x0:x1], (alpha * 255.0).astype(np.uint8)])
    return Cutout(rgba=rgba, x=int(x0), y=int(y0))


def read_frame_rgb(video_path: Path, t_sec: float, size: tuple[int, int]) -> np.ndarray | None:
    cap = cv2.VideoCapture(str(video_path))
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t_sec) * 1000.0)
        ok, bgr = cap.read()
    finally:
        cap.release()
    if not ok or bgr is None:
        return None
    return cv2.cvtColor(cv2.resize(bgr, size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)


def enemy_cutout_at_kill(model, video_path: Path, kill_sec: float, size: tuple[int, int]) -> Cutout | None:
    for offset in SAMPLE_OFFSETS_SEC:
        frame = read_frame_rgb(video_path, kill_sec - offset, size)
        if frame is None:
            continue
        mask = best_enemy_mask(model, frame)
        if mask is not None:
            return to_cutout(frame, mask)
    return None
