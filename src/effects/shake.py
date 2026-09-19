from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect


@register_clip_effect("shake")
@dataclass
class ShakeEffect(ClipEffect):
    enabled: bool = True
    amplitude_px: int = 6
    decay_rate: float = 0.85
    duration_frames: int = 8

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled or self.amplitude_px <= 0 or self.duration_frames <= 0:
            return clip

        fps = max(1, int(ctx.fps))
        duration_sec = self.duration_frames / fps

        # Anchor shake around kill timestamp when available; otherwise keep at clip start.
        center_t = float(ctx.kill_timestamp) if ctx.kill_timestamp is not None else 0.0
        start_t = max(0.0, center_t - duration_sec / 2.0)
        end_t = start_t + duration_sec

        # Deterministic pseudo-random per-frame offsets (no global RNG, stable across renders).
        seed = int(round((float(ctx.kill_timestamp or 0.0) + float(ctx.clip_duration)) * 1000.0)) & 0xFFFFFFFF

        def _rand_unit(frame_idx: int, axis: int) -> float:
            # Simple hash -> [0,1) then scale to [-1,1]
            x = (seed ^ (frame_idx * 1103515245) ^ (axis * 12345)) & 0xFFFFFFFF
            x = (x * 1664525 + 1013904223) & 0xFFFFFFFF
            return (float(x) / 2**32) * 2.0 - 1.0

        def transform(get_frame, t: float):
            frame = get_frame(t)
            if t < start_t or t > end_t:
                return frame
            idx = int(round((t - start_t) * fps))
            amp = float(self.amplitude_px) * (float(self.decay_rate) ** idx)
            ox = int(round(amp * _rand_unit(idx, 0)))
            oy = int(round(amp * _rand_unit(idx, 1)))
            h, w = frame.shape[:2]
            M = np.float32([[1, 0, ox], [0, 1, oy]])
            return cv2.warpAffine(frame, M, (w, h), borderMode=cv2.BORDER_REFLECT)

        return clip.transform(transform)
