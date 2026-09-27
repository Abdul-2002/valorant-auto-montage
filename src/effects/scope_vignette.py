from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect


@lru_cache(maxsize=4)
def _radial_distance(h: int, w: int) -> np.ndarray:
    """Distance from screen center in half-height units (circle, not aspect ellipse)."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    half = max(1.0, h / 2.0)
    return np.sqrt(((xx - w / 2.0) / half) ** 2 + ((yy - h / 2.0) / half) ** 2)


def _ease_out(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return 1.0 - (1.0 - u) ** 3


@register_clip_effect("scope_vignette")
@dataclass
class ScopeVignetteEffect(ClipEffect):
    """Scope mask for sniper kills: a black ring closes in on scope-in and snaps open on the kill."""

    enabled: bool = True
    pre_sec: float = 0.35
    release_sec: float = 0.12
    inner_radius: float = 0.92
    darkness: float = 0.92
    feather: float = 0.05

    def _radius_and_strength(self, t: float, kill_t: float, open_r: float) -> tuple[float, float]:
        inner = float(self.inner_radius)
        if t < kill_t:
            u = (t - (kill_t - float(self.pre_sec))) / max(1e-6, float(self.pre_sec))
            return open_r + (inner - open_r) * _ease_out(u), 1.0
        v = (t - kill_t) / max(1e-6, float(self.release_sec))
        return inner + (open_r - inner) * min(1.0, v), max(0.0, 1.0 - v)

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled or ctx.kill_timestamp is None:
            return clip
        kill_t = float(ctx.kill_timestamp)
        start_t, end_t = kill_t - float(self.pre_sec), kill_t + float(self.release_sec)

        def transform(get_frame, t: float):
            frame = get_frame(t)
            if t < start_t or t > end_t:
                return frame
            h, w = frame.shape[:2]
            dist = _radial_distance(h, w)
            open_r = float(dist.max())
            radius, strength = self._radius_and_strength(float(t), kill_t, open_r)
            alpha = np.clip((dist - radius) / max(1e-6, float(self.feather)), 0.0, 1.0)
            alpha = (alpha * float(self.darkness) * strength)[..., None]
            return (frame.astype(np.float32) * (1.0 - alpha)).astype(np.uint8)

        return clip.transform(transform)
