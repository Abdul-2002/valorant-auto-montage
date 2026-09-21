from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect


@register_clip_effect("letterbox")
@dataclass
class LetterboxEffect(ClipEffect):
    enabled: bool = True
    bar_frac: float = 0.08
    duration_sec: float = 1.2

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled or ctx.kill_timestamp is None:
            return clip

        base_dur = float(getattr(clip, "duration", None) or ctx.clip_duration)
        dur = min(float(self.duration_sec), base_dur)
        center_t = float(ctx.kill_timestamp)
        start_t = max(0.0, center_t - dur * 0.35)
        end_t = min(base_dur, center_t + dur * 0.65)
        bar_frac = float(self.bar_frac)

        def transform(get_frame, t: float):
            frame = get_frame(t)
            if t < start_t or t > end_t:
                return frame
            h, w = frame.shape[:2]
            u = (float(t) - start_t) / max(1e-9, end_t - start_t)
            # Ease bars in then hold then ease out.
            if u < 0.2:
                a = u / 0.2
            elif u > 0.8:
                a = (1.0 - u) / 0.2
            else:
                a = 1.0
            bar = int(h * bar_frac * a)
            if bar <= 0:
                return frame
            out = frame.copy()
            out[:bar, :] = 0
            out[h - bar :, :] = 0
            return out

        return clip.transform(transform)
