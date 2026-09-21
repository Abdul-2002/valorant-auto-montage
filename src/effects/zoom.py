from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from moviepy.video.VideoClip import VideoClip
from moviepy.video.fx import Resize

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect


def _ease_out_cubic(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1.0 - (1.0 - x) ** 3


def _ease_in_cubic(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * x


@register_clip_effect("zoom")
@dataclass
class ZoomEffect(ClipEffect):
    enabled: bool = True
    max_zoom: float = 1.32
    duration_sec: float = 0.45
    crash_in_frac: float = 0.35
    easing: str = "ease_out_quad"
    center: str = "screen_center"

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled:
            return clip

        base_dur = float(getattr(clip, "duration", None) or ctx.clip_duration)
        dur = min(float(self.duration_sec), max(0.05, base_dur))
        center_t = float(ctx.kill_timestamp) if ctx.kill_timestamp is not None else base_dur / 2.0
        half = dur / 2.0
        start_t = center_t - half
        end_t = center_t + half
        in_frac = float(self.crash_in_frac)
        peak = float(self.max_zoom)

        def scale(t: float) -> float:
            if t <= start_t or t >= end_t:
                return 1.0
            u = (t - start_t) / max(1e-9, end_t - start_t)
            if u <= in_frac:
                p = _ease_in_cubic(u / max(1e-9, in_frac))
                return 1.0 + (peak - 1.0) * p
            p = _ease_out_cubic((u - in_frac) / max(1e-9, 1.0 - in_frac))
            return peak - (peak - 1.0) * p

        return clip.with_effects([Resize(scale)])
