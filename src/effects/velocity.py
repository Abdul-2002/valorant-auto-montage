from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect
from src.pipeline.time_remap import make_remap_fn


def _ease_in_out_cubic(x: float) -> float:
    x = max(0.0, min(1.0, float(x)))
    return 4 * x * x * x if x < 0.5 else 1 - ((-2 * x + 2) ** 3) / 2


@register_clip_effect("velocity")
@dataclass
class VelocityEffect(ClipEffect):
    """Retime a clip. Script clips carry knots that pin every kill frame to its beat."""

    enabled: bool = True
    kill_slowmo_factor: float = 0.4
    kill_slowmo_duration_sec: float = 0.9
    slowmo_min_unique_fps: float = 30.0
    approach_speed: float = 1.15
    exit_speed: float = 1.35
    transition_speedup_factor: float = 2.0
    easing: str = "ease_in_out_cubic"

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled:
            return clip
        knots = ctx.config.get("_time_knots")
        src_dur = ctx.config.get("_src_duration_sec")
        if knots and src_dur is not None:
            src_max = max(0.0, float(src_dur) - 1.0 / max(1, int(ctx.fps)))
            return clip.time_transform(make_remap_fn(knots, src_max=src_max), apply_to=["mask", "audio"])
        if ctx.kill_timestamp is None or self.kill_slowmo_duration_sec <= 0.0:
            return clip
        return self._centered_slowmo(clip, float(ctx.kill_timestamp))

    def _centered_slowmo(self, clip: VideoClip, kill_t: float) -> VideoClip:
        """Fallback for scripts without knots: eased slow window around the kill."""
        half = float(self.kill_slowmo_duration_sec) / 2.0
        slow_start = max(0.0, kill_t - half)
        slow_end = min(float(clip.duration), kill_t + half)
        span = max(1e-9, slow_end - slow_start)
        factor = float(self.kill_slowmo_factor)
        trans_speed = 1.0 if float(clip.duration or 0.0) <= 2.0 else float(self.transition_speedup_factor)

        def time_map(t: float) -> float:
            if t < slow_start:
                return float(t)
            if t <= slow_end:
                return slow_start + span * factor * _ease_in_out_cubic((t - slow_start) / span)
            return slow_end + (t - slow_end) * trans_speed

        return clip.time_transform(time_map)
