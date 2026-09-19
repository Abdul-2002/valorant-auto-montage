from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from moviepy.video.VideoClip import VideoClip
from moviepy.video.fx import Resize

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect


def _ease_out_quad(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) * (1 - x)


@register_clip_effect("zoom")
@dataclass
class ZoomEffect(ClipEffect):
    enabled: bool = True
    max_zoom: float = 1.25
    duration_sec: float = 0.3
    easing: str = "ease_out_quad"
    center: str = "screen_center"

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled:
            return clip

        base_dur = getattr(clip, "duration", None) or ctx.clip_duration
        dur = min(float(self.duration_sec), float(base_dur))

        # Zoom should be time-localized around the kill moment, not always from clip start.
        # We keep this v1-friendly and deterministic: a symmetric ease-in/out window around
        # `kill_timestamp` (or around the clip midpoint if kill time is unknown).
        center_t = float(ctx.kill_timestamp) if ctx.kill_timestamp is not None else float(base_dur) / 2.0
        half = max(0.0, dur / 2.0)
        start_t = center_t - half
        end_t = center_t + half

        def scale(t: float) -> float:
            if dur <= 0:
                return float(self.max_zoom)

            # Outside the window: no zoom.
            if t <= start_t or t >= end_t:
                return 1.0

            # Map t into [0, 1] inside the window, peak at 0.5.
            u = (t - start_t) / max(1e-9, (end_t - start_t))
            tri = 1.0 - abs(2.0 * u - 1.0)  # 0..1..0
            p = _ease_out_quad(tri)
            return 1.0 + (float(self.max_zoom) - 1.0) * p

        # MoviePy v2 uses with_effects; but Resize works as effect class.
        return clip.with_effects([Resize(scale)])
