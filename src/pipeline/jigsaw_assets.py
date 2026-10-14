"""Bake jigsaw piece maps: the incoming clip's gun plus SAM scene segments.

The jigsaw tutorial masks each scene element (gun, crate, walls) by hand. Here
the gun comes from the weapon-box SAM prompt (or a gun-shaped SAM segment in
the weapon box) and the other elements from SAM's prompt-free segmentation of
the incoming clip's first frame, then from point prompts at the frame edges.
Without usable segments the fixed layout's edge strips stand in for them.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from src.ai.schema import MontageScript
from src.detection.enemy_cutout import CutoutError, load_sam, read_frame_rgb
from src.effects.transitions.jigsaw import REST_LABEL, WEAPON_LABEL, fixed_piece_labels
from src.pipeline.weapon_assets import WEAPON_BOX_FRAC, release_gpu_cache, valid_weapon_mask, weapon_mask_at

log = logging.getLogger(__name__)

MIN_SEGMENT_FRAC = 0.02
MAX_SEGMENT_FRAC = 0.45
MAX_SEGMENTS = 3
# The gun and its arms land as one piece, so big skins count (Phantom close-up ~12%).
JIGSAW_GUN_AREA_RANGE = (0.01, 0.16)
_GUN_ZONE_MIN_IN_BOX = 0.8
# Left/right walls and the upper centre; y=0.25 clears the HUD score bar.
_ELEMENT_POINTS_FRAC = ((0.08, 0.5), (0.92, 0.5), (0.5, 0.25))
# SAM returns nested masks; skip one mostly covered by already chosen pieces.
_MAX_OVERLAP_FRAC = 0.5
_OPEN_KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))


def _largest_component(mask: np.ndarray) -> np.ndarray:
    opened = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, _OPEN_KERNEL)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    if n <= 1:
        return np.zeros(mask.shape, dtype=bool)
    return labels == int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) + 1


def pick_scene_segments(masks: list[np.ndarray], taken: np.ndarray) -> list[np.ndarray]:
    """Up to MAX_SEGMENTS disjoint mid-size segments, largest first."""
    used = taken.copy()
    chosen: list[np.ndarray] = []
    for m in sorted(masks, key=lambda m: -float(m.mean())):
        if len(chosen) >= MAX_SEGMENTS:
            break
        if not MIN_SEGMENT_FRAC <= float(m.mean()) <= MAX_SEGMENT_FRAC:
            continue
        if float((m & used).sum()) > _MAX_OVERLAP_FRAC * float(m.sum()):
            continue
        seg = _largest_component(m & ~used)
        if float(seg.mean()) < MIN_SEGMENT_FRAC:
            continue
        chosen.append(seg)
        used |= seg
    return chosen


def gun_zone_segment(masks: list[np.ndarray]) -> np.ndarray | None:
    """Largest gun-shaped segment inside the weapon box, for when the box prompt fails."""
    if not masks:
        return None
    h, w = masks[0].shape
    x0f, y0f, x1f, y1f = WEAPON_BOX_FRAC
    box = np.zeros((h, w), dtype=bool)
    box[int(y0f * h) : int(y1f * h), int(x0f * w) : int(x1f * w)] = True
    for m in sorted(masks, key=lambda m: -float(m.mean())):
        seg = _largest_component(m)
        if not seg.any() or float((seg & box).sum()) < _GUN_ZONE_MIN_IN_BOX * float(seg.sum()):
            continue
        if valid_weapon_mask(seg, JIGSAW_GUN_AREA_RANGE):
            return seg
    return None


def compose_piece_labels(h: int, w: int, weapon: np.ndarray | None, segments: list[np.ndarray]) -> np.ndarray:
    """Label map: weapon = 1, segments = 2.. in arrival order, rest = 0."""
    if segments:
        labels = np.zeros((h, w), dtype=np.uint8)
        for k, seg in enumerate(segments):
            labels[seg] = WEAPON_LABEL + 1 + k
    else:
        labels = fixed_piece_labels(h, w)
        if weapon is not None:
            labels[labels == WEAPON_LABEL] = REST_LABEL
    if weapon is not None:
        labels[weapon] = WEAPON_LABEL
    return labels


def _sam_masks(model, frame_rgb: np.ndarray) -> list[np.ndarray]:
    h, w = frame_rgb.shape[:2]
    res = model(np.ascontiguousarray(frame_rgb[:, :, ::-1]), verbose=False)
    if not res or res[0].masks is None:
        return []
    out = []
    for m in res[0].masks.data.cpu().numpy():
        if m.shape != (h, w):
            m = cv2.resize(m.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)
        out.append(m.astype(bool))
    return out


def _sam_point_masks(model, frame_rgb: np.ndarray) -> list[np.ndarray]:
    """All multimask outputs (part to whole object) for each edge point prompt."""
    h, w = frame_rgb.shape[:2]
    bgr = np.ascontiguousarray(frame_rgb[:, :, ::-1])
    out: list[np.ndarray] = []
    for fx, fy in _ELEMENT_POINTS_FRAC:
        res = model.predictor(bgr, points=[[int(fx * w), int(fy * h)]], labels=[1], multimask_output=True)
        if res and res[0].masks is not None:
            out.extend(m.astype(bool) for m in res[0].masks.data.cpu().numpy())
    return out


def build_piece_map(model, video_path: Path, src_sec: float, size: tuple[int, int]) -> np.ndarray | None:
    frame = read_frame_rgb(video_path, src_sec, size)
    if frame is None:
        return None
    h, w = frame.shape[:2]
    masks = _sam_masks(model, frame)
    weapon = weapon_mask_at(model, video_path, src_sec, size, JIGSAW_GUN_AREA_RANGE, multimask=True)
    if weapon is None:
        weapon = gun_zone_segment(masks)
    taken = weapon if weapon is not None else np.zeros((h, w), dtype=bool)
    segments = pick_scene_segments(masks, taken) or pick_scene_segments(_sam_point_masks(model, frame), taken)
    return compose_piece_labels(h, w, weapon, segments)


def _head_src_sec(clip) -> float:
    """Source second shown at the clip's first output frame."""
    knots = clip.time_knots or []
    return float(clip.start_sec) + (float(knots[0][1]) if knots else 0.0)


def attach_jigsaw_pieces(
    script: MontageScript,
    *,
    video_paths: list[Path],
    out_dir: Path,
    resolution: tuple[int, int],
    sam_model_path: Path,
) -> MontageScript:
    """Bake a piece map for every jigsaw cut; the render uses the fixed layout without one."""
    slots = [
        i
        for i, c in enumerate(script.clips[:-1])
        if c.transition_to_next is not None and c.transition_to_next.type == "jigsaw"
    ]
    if not slots:
        return script
    try:
        model = load_sam(sam_model_path)
    except CutoutError:
        log.exception("jigsaw_assets: SAM unavailable; jigsaws render with the fixed layout")
        return script
    piece_dir = out_dir / "elements"
    piece_dir.mkdir(parents=True, exist_ok=True)
    clips = list(script.clips)
    for i in slots:
        incoming = clips[i + 1]
        labels = build_piece_map(model, video_paths[incoming.video_index], _head_src_sec(incoming), resolution)
        if labels is None:
            log.info("jigsaw_assets: cut %d->%d: incoming frame unreadable; fixed layout", i, i + 1)
            continue
        path = piece_dir / f"clip_{i + 1:02d}_pieces.png"
        cv2.imwrite(str(path), labels)
        transition = clips[i].transition_to_next.model_copy(update={"asset_path": str(path)})
        clips[i] = clips[i].model_copy(update={"transition_to_next": transition})
        log.info(
            "jigsaw_assets: cut %d->%d: pieces=%s weapon=%s",
            i,
            i + 1,
            sorted(int(v) for v in np.unique(labels) if v != REST_LABEL),
            bool((labels == WEAPON_LABEL).any()),
        )
    del model
    release_gpu_cache()
    return script.model_copy(update={"clips": clips})
