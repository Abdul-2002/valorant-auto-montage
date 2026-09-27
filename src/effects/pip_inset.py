from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect

_REFERENCE_HEIGHT = 1080.0
_BORDER_PX = 4
_POP_SEC, _OUT_SEC = 0.18, 0.2


def _crosshair_crop(frame_bgr: np.ndarray, zoom: float, size: tuple[int, int]) -> np.ndarray:
    """Zoomed 16:9 crop around screen center (the kill happens under the crosshair)."""
    h, w = frame_bgr.shape[:2]
    cw, ch = int(w / zoom), int(h / zoom)
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    crop = frame_bgr[y0 : y0 + ch, x0 : x0 + cw]
    return cv2.cvtColor(cv2.resize(crop, size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)


def read_card_frames(
    video_path: Path, *, start_sec: float, end_sec: float, step_sec: float, zoom: float, size: tuple[int, int]
) -> list[np.ndarray]:
    """Source frames at ``start..end`` every ``step`` seconds (sequential decode, no backwards seeks)."""
    cap = cv2.VideoCapture(str(video_path))
    frames: list[np.ndarray] = []
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, start_sec) * 1000.0)
        want = max(0.0, start_sec)
        while want <= end_sec + 1e-6:
            ok, bgr = cap.read()
            if not ok:
                break
            if cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0 + 1e-3 < want:
                continue
            frames.append(_crosshair_crop(bgr, zoom, size))
            want += step_sec
    finally:
        cap.release()
    return frames


def _ease_out_back(u: float) -> float:
    u = min(1.0, max(0.0, u)) - 1.0
    return 1.0 + 2.2 * u**3 + 1.2 * u**2


def _framed(card: np.ndarray) -> np.ndarray:
    return cv2.copyMakeBorder(card, _BORDER_PX, _BORDER_PX, _BORDER_PX, _BORDER_PX, cv2.BORDER_CONSTANT, value=(255, 255, 255))


@register_clip_effect("pip_inset")
@dataclass
class PipInsetEffect(ClipEffect):
    """Picture-in-picture card after the kill (frozen crosshair zoom, or a slow-mo replay)."""

    enabled: bool = True
    style: str = "freeze_inset"
    delay_sec: float = 0.08
    hold_sec: float = 1.0
    zoom: float = 2.2
    replay_window_sec: float = 0.6
    replay_speed: float = 0.5
    width_px: int = 520

    def _frames(self, video: Path, kill_src: float, fps: int, size: tuple[int, int]) -> list[np.ndarray]:
        if self.style == "replay_inset":
            step = float(self.replay_speed) / max(1, fps)
            start = kill_src - float(self.replay_window_sec)
            return read_card_frames(video, start_sec=start, end_sec=kill_src, step_sec=step, zoom=self.zoom, size=size)
        return read_card_frames(video, start_sec=kill_src, end_sec=kill_src, step_sec=1.0, zoom=self.zoom, size=size)

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        video, kill_src = ctx.config.get("_video_path"), ctx.config.get("_kill_src_sec")
        if not self.enabled or ctx.kill_timestamp is None or not video or kill_src is None:
            return clip
        h = int(ctx.resolution[1])
        cw = int(round(self.width_px * h / _REFERENCE_HEIGHT)) & ~1
        size = (cw, int(round(cw * 9 / 16)) & ~1)
        frames = [_framed(f) for f in self._frames(Path(video), float(kill_src), int(ctx.fps), size)]
        if not frames:
            return clip
        t_in = float(ctx.kill_timestamp) + float(self.delay_sec)
        t_out = t_in + float(self.hold_sec)
        fps = max(1, int(ctx.fps))

        def transform(get_frame, t: float):
            frame = get_frame(t)
            if not t_in <= t < t_out + _OUT_SEC:
                return frame
            card = frames[min(len(frames) - 1, int((float(t) - t_in) * fps))]
            scale = 0.6 + 0.4 * _ease_out_back((float(t) - t_in) / _POP_SEC)
            fade = 1.0 - max(0.0, (float(t) - t_out) / _OUT_SEC)
            return _place(frame, card, scale=scale, alpha=fade, drop=(1.0 - fade) * 40.0)

        return clip.transform(transform)


def _place(frame: np.ndarray, card: np.ndarray, *, scale: float, alpha: float, drop: float) -> np.ndarray:
    """Bottom-center placement (inside the 9:16 crop), with pop scale and slide-out."""
    if alpha <= 0.01:
        return frame
    if abs(scale - 1.0) > 1e-3:
        card = cv2.resize(card, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    fh, fw = frame.shape[:2]
    ch, cw = card.shape[:2]
    x0 = (fw - cw) // 2
    y0 = int(fh * 0.78 - ch / 2 + drop)
    y1, x1 = min(fh, y0 + ch), x0 + cw
    if y0 >= fh or x0 < 0:
        return frame
    out = frame.copy()
    roi = out[y0:y1, x0:x1].astype(np.float32)
    out[y0:y1, x0:x1] = (roi * (1.0 - alpha) + card[: y1 - y0].astype(np.float32) * alpha).astype(np.uint8)
    return out
