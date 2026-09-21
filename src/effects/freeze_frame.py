from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect


@register_clip_effect("freeze_frame")
@dataclass
class FreezeFrameEffect(ClipEffect):
    """Hold the kill frame briefly without changing clip duration."""

    enabled: bool = True
    duration_sec: float = 0.08

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled or ctx.kill_timestamp is None:
            return clip

        base_dur = float(getattr(clip, "duration", None) or ctx.clip_duration)
        freeze = min(float(self.duration_sec), max(0.02, base_dur * 0.15))
        kill_t = float(ctx.kill_timestamp)
        # Map [kill, kill+freeze] -> kill source time; compress the rest after.
        # Simpler duration-preserving approach: sample kill frame during freeze window.
        end = min(base_dur, kill_t + freeze)

        def time_map(t: Any) -> Any:
            tt = np.asarray(t, dtype=np.float64)
            src = np.where((tt >= kill_t) & (tt <= end), kill_t, tt)
            src = np.clip(src, 0.0, max(0.0, base_dur - 1e-3))
            if np.ndim(t) == 0:
                return float(src)
            return src

        return clip.time_transform(time_map, apply_to=["mask", "audio"])
