from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect


@register_clip_effect("rgb_split")
@dataclass
class RgbSplitEffect(ClipEffect):
    enabled: bool = True
    duration_sec: float = 0.18
    offset_px: int = 4

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled or ctx.kill_timestamp is None:
            return clip

        base_dur = float(getattr(clip, "duration", None) or ctx.clip_duration)
        dur = min(float(self.duration_sec), base_dur)
        center_t = float(ctx.kill_timestamp)
        start_t = max(0.0, center_t - dur * 0.3)
        end_t = min(base_dur, center_t + dur * 0.7)
        off = int(self.offset_px)

        def transform(get_frame, t: float):
            frame = get_frame(t)
            if t < start_t or t > end_t:
                return frame
            u = (float(t) - start_t) / max(1e-9, end_t - start_t)
            a = int(round(off * float(np.sin(np.pi * u))))
            if a == 0:
                return frame
            r = np.roll(frame[:, :, 0], a, axis=1)
            g = frame[:, :, 1]
            b = np.roll(frame[:, :, 2], -a, axis=1)
            return np.stack([r, g, b], axis=-1)

        return clip.transform(transform)
