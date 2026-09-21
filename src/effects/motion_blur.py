from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect


@register_clip_effect("motion_blur")
@dataclass
class MotionBlurEffect(ClipEffect):
    enabled: bool = True
    duration_sec: float = 0.25
    amount_px: int = 28

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled or ctx.kill_timestamp is None:
            return clip

        base_dur = float(getattr(clip, "duration", None) or ctx.clip_duration)
        dur = min(float(self.duration_sec), base_dur)
        center_t = float(ctx.kill_timestamp)
        start_t = max(0.0, center_t - dur * 0.5)
        end_t = min(base_dur, center_t + dur * 0.5)
        amount = max(1, int(self.amount_px))

        def transform(get_frame, t: float):
            frame = get_frame(t)
            if t < start_t or t > end_t:
                return frame
            u = (float(t) - start_t) / max(1e-9, end_t - start_t)
            strength = float(np.sin(np.pi * u))
            k = max(1, int(round(amount * strength)))
            if k <= 1:
                return frame
            kernel = np.zeros((1, k), dtype=np.float32)
            kernel[0, :] = 1.0 / k
            blurred = cv2.filter2D(frame, -1, kernel)
            return blurred

        return clip.transform(transform)
