"""Neon weapon outline through the post-kill slow-mo (reference-style rotoscope).

Contours come from pipeline.weapon_assets (cleaned multi-frame SAM keyframes).
Between SAM anchors, points are optical-flow warped so the outline tracks the
weapon through the slow-mo window. Runs in frame-space before camera effects.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect

log = logging.getLogger(__name__)

_FLOW_SCALE = 0.5  # downsample for Farneback speed


def _as_contours(raw: list) -> tuple[np.ndarray, ...]:
    return tuple(np.asarray(c, dtype=np.int32).reshape(-1, 1, 2) for c in raw if len(c) >= 3)


@lru_cache(maxsize=16)
def _load_asset(asset_path: str) -> dict[str, Any]:
    try:
        return json.loads(open(asset_path, encoding="utf-8").read())
    except OSError:
        log.warning("gun_outline: asset unreadable: %s", asset_path)
        return {}


def _load_contours(asset_path: str) -> tuple[np.ndarray, ...]:
    payload = _load_asset(asset_path)
    return _as_contours(payload.get("contours", []))


def out_rel_to_src_offset(t_rel_out: float, slowmo_factor: float) -> float:
    """Map clip-relative time from the kill to source-relative offset."""
    if t_rel_out <= 0.0:
        return float(t_rel_out)
    return float(t_rel_out) * max(float(slowmo_factor), 1e-3)


def warp_contours_with_flow(
    contours: tuple[np.ndarray, ...], flow: np.ndarray
) -> tuple[np.ndarray, ...]:
    """Displace contour points by a dense optical-flow field (full-res HxWx2)."""
    if flow.size == 0 or not contours:
        return contours
    h, w = flow.shape[:2]
    out: list[np.ndarray] = []
    for c in contours:
        pts = c.reshape(-1, 2).astype(np.float32)
        xs = np.clip(pts[:, 0], 0, w - 1).astype(np.int32)
        ys = np.clip(pts[:, 1], 0, h - 1).astype(np.int32)
        disp = flow[ys, xs]
        warped = pts + disp
        warped[:, 0] = np.clip(warped[:, 0], 0, w - 1)
        warped[:, 1] = np.clip(warped[:, 1], 0, h - 1)
        out.append(warped.astype(np.int32).reshape(-1, 1, 2))
    return tuple(out)


def _read_gray(cap: cv2.VideoCapture, t_sec: float, size: tuple[int, int]) -> np.ndarray | None:
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t_sec) * 1000.0)
    ok, bgr = cap.read()
    if not ok or bgr is None:
        return None
    if (bgr.shape[1], bgr.shape[0]) != size:
        bgr = cv2.resize(bgr, size, interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def _flow_between(prev: np.ndarray, nxt: np.ndarray) -> np.ndarray:
    """Full-resolution flow from prev→nxt via downsampled Farneback."""
    small_prev = cv2.resize(prev, None, fx=_FLOW_SCALE, fy=_FLOW_SCALE, interpolation=cv2.INTER_AREA)
    small_nxt = cv2.resize(nxt, None, fx=_FLOW_SCALE, fy=_FLOW_SCALE, interpolation=cv2.INTER_AREA)
    flow_s = cv2.calcOpticalFlowFarneback(
        small_prev, small_nxt, None, 0.5, 3, 15, 3, 5, 1.2, 0
    )
    flow = cv2.resize(flow_s, (prev.shape[1], prev.shape[0]), interpolation=cv2.INTER_LINEAR)
    flow /= _FLOW_SCALE
    return flow


def _nearest_keyframe(
    keyframes: list[tuple[float, tuple[np.ndarray, ...]]], src_offset: float
) -> tuple[float, tuple[np.ndarray, ...]]:
    return min(keyframes, key=lambda kf: abs(kf[0] - src_offset))


def precompute_tracked_contours(
    *,
    asset_path: str,
    video_path: str | None,
    kill_src_sec: float | None,
    kill_out: float,
    pre_sec: float,
    window_sec: float,
    fps: int,
) -> dict[int, tuple[np.ndarray, ...]]:
    """Build per-frame-index contours across the outline window (SAM anchors + flow)."""
    payload = _load_asset(asset_path)
    primary = _as_contours(payload.get("contours", []))
    if not primary:
        return {}
    slowmo = float(payload.get("slowmo_factor", 0.45) or 0.45)
    raw_kfs = payload.get("keyframes") or []
    keyframes: list[tuple[float, tuple[np.ndarray, ...]]] = []
    for kf in raw_kfs:
        cont = _as_contours(kf.get("contours", []))
        if cont:
            keyframes.append((float(kf["src_offset"]), cont))
    if not keyframes:
        keyframes = [(0.0, primary)]

    start, end = kill_out - float(pre_sec), kill_out + float(window_sec)
    n_frames = max(1, int(round((end - start) * max(fps, 1))) + 1)
    cache: dict[int, tuple[np.ndarray, ...]] = {}

    can_flow = bool(video_path) and kill_src_sec is not None and Path(video_path).is_file()
    if not can_flow:
        for i in range(n_frames):
            t = start + i / max(fps, 1)
            src_off = out_rel_to_src_offset(t - kill_out, slowmo)
            cache[i] = _nearest_keyframe(keyframes, src_off)[1]
        return cache

    cap = cv2.VideoCapture(str(video_path))
    try:
        size = tuple(int(x) for x in payload.get("frame", [1920, 1080]))
        # Warm gray cache for SAM anchor times + each output sample.
        gray_at: dict[float, np.ndarray] = {}

        def gray(src_off: float) -> np.ndarray | None:
            key = round(src_off, 3)
            if key in gray_at:
                return gray_at[key]
            g = _read_gray(cap, float(kill_src_sec) + src_off, (size[0], size[1]))
            if g is not None:
                gray_at[key] = g
            return g

        for off, _ in keyframes:
            gray(off)

        for i in range(n_frames):
            t = start + i / max(fps, 1)
            src_off = out_rel_to_src_offset(t - kill_out, slowmo)
            anchor_off, anchor_cont = _nearest_keyframe(keyframes, src_off)
            if abs(anchor_off - src_off) < 1e-3:
                cache[i] = anchor_cont
                continue
            g0 = gray(anchor_off)
            g1 = gray(src_off)
            if g0 is None or g1 is None:
                cache[i] = anchor_cont
                continue
            flow = _flow_between(g0, g1)
            cache[i] = warp_contours_with_flow(anchor_cont, flow)
    finally:
        cap.release()
    return cache


def draw_outline(
    frame: np.ndarray,
    contours: tuple[np.ndarray, ...],
    *,
    color: tuple[int, int, int],
    thickness: int,
    glow_blur_px: int,
    alpha: float,
) -> np.ndarray:
    """Additive neon outline: crisp polyline core + blurred glow halo."""
    if alpha <= 0.01 or not contours:
        return frame
    layer = np.zeros_like(frame)
    cv2.polylines(layer, list(contours), isClosed=True, color=color, thickness=thickness, lineType=cv2.LINE_AA)
    glow = cv2.GaussianBlur(layer, (0, 0), max(1.0, glow_blur_px / 3.0))
    boosted = np.clip(layer.astype(np.float32) + glow.astype(np.float32) * 1.6, 0.0, 255.0)
    out = frame.astype(np.float32) + boosted * float(alpha)
    return np.clip(out, 0, 255).astype(np.uint8)


@register_clip_effect("gun_outline")
@dataclass
class GunOutlineEffect(ClipEffect):
    enabled: bool = True
    asset_path: Optional[str] = None
    pre_sec: float = 0.1
    window_sec: float = 0.6
    glow_rgb: tuple[int, int, int] = (90, 220, 255)
    thickness_px: int = 3
    glow_blur_px: int = 15
    max_alpha: float = 0.9

    def _alpha(self, t: float, kill: float) -> float:
        """Ramp in before the kill, hold through the slow-mo, fade out."""
        start, end = kill - float(self.pre_sec), kill + float(self.window_sec)
        if t < start or t > end:
            return 0.0
        if t < kill:
            return self.max_alpha * (t - start) / max(self.pre_sec, 1e-9)
        hold = self.window_sec * 0.55
        rel = t - kill
        if rel <= hold:
            return self.max_alpha
        return self.max_alpha * (1.0 - (rel - hold) / max(self.window_sec - hold, 1e-9))

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled or ctx.kill_timestamp is None or not self.asset_path:
            return clip
        if not _load_contours(self.asset_path):
            return clip
        kill = float(ctx.kill_timestamp)
        start = kill - float(self.pre_sec)
        fps = max(int(ctx.fps), 1)
        cfg = ctx.config or {}
        tracked = precompute_tracked_contours(
            asset_path=str(self.asset_path),
            video_path=cfg.get("_video_path"),
            kill_src_sec=cfg.get("_kill_src_sec"),
            kill_out=kill,
            pre_sec=float(self.pre_sec),
            window_sec=float(self.window_sec),
            fps=fps,
        )
        fallback = _load_contours(self.asset_path)

        def transform(get_frame, t: float):
            frame = get_frame(t)
            a = self._alpha(float(t), kill)
            if a <= 0.01:
                return frame
            idx = int(round((float(t) - start) * fps))
            contours = tracked.get(idx, fallback)
            return draw_outline(
                frame,
                contours,
                color=self.glow_rgb,
                thickness=int(self.thickness_px),
                glow_blur_px=int(self.glow_blur_px),
                alpha=a,
            )

        return clip.transform(transform)
