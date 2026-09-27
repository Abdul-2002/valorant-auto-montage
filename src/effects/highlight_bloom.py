from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import cv2
import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect


@lru_cache(maxsize=4)
def _weapon_region(h: int, w: int) -> np.ndarray:
    """Weight peaking in the lower-right quadrant where the FPS viewmodel sits."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    wx = np.clip((xx / max(1, w - 1) - 0.45) / 0.55, 0.0, 1.0)
    wy = np.clip((yy / max(1, h - 1) - 0.40) / 0.60, 0.0, 1.0)
    return 0.35 + 0.65 * (wx * wy)


def bright_pass_glow(img: np.ndarray, *, threshold: float, blur_px: int, weapon_bias: float) -> np.ndarray:
    """Blurred glow of pixels brighter than ``threshold`` (img is float RGB in 0..1)."""
    luma = 0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2]
    mask = np.clip((luma - threshold) / max(1e-6, 1.0 - threshold), 0.0, 1.0)
    if weapon_bias > 0.0:
        h, w = luma.shape
        mask = mask * ((1.0 - weapon_bias) + weapon_bias * _weapon_region(h, w))
    blur = max(1, int(blur_px) | 1)
    return cv2.GaussianBlur(img * mask[..., None], (blur, blur), 0)


def screen_add(img: np.ndarray, glow: np.ndarray, amount: float) -> np.ndarray:
    """Screen-ish blend: base + glow * (1 - base)."""
    return np.clip(img + glow * float(amount) * (1.0 - img), 0.0, 1.0)


@register_clip_effect("highlight_bloom")
@dataclass
class HighlightBloomEffect(ClipEffect):
    """Glow only bright pixels (skins, muzzle, utility) — automated gun-brightness stand-in."""

    enabled: bool = True
    duration_sec: float = 0.55
    luma_threshold: float = 0.62
    blur_px: int = 18
    intensity: float = 0.85
    weapon_bias: float = 0.35

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled or ctx.kill_timestamp is None:
            return clip

        base_dur = float(getattr(clip, "duration", None) or ctx.clip_duration)
        dur = min(float(self.duration_sec), base_dur)
        center_t = float(ctx.kill_timestamp)
        start_t = max(0.0, center_t - dur * 0.3)
        end_t = min(base_dur, center_t + dur * 0.7)

        def transform(get_frame, t: float):
            frame = get_frame(t)
            if t < start_t or t > end_t:
                return frame
            u = (float(t) - start_t) / max(1e-9, end_t - start_t)
            fade = float(np.clip(1.0 - abs(2.0 * u - 1.0), 0.0, 1.0))
            if fade < 1e-3:
                return frame
            img = frame.astype(np.float32) / 255.0
            glow = bright_pass_glow(
                img, threshold=float(self.luma_threshold), blur_px=int(self.blur_px), weapon_bias=float(self.weapon_bias)
            )
            return (screen_add(img, glow, float(self.intensity) * fade) * 255.0).astype(np.uint8)

        return clip.transform(transform)
