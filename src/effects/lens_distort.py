from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect


@register_clip_effect("lens_distort")
@dataclass
class LensDistortEffect(ClipEffect):
    enabled: bool = True
    duration_sec: float = 0.35
    strength: float = 0.18

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled or ctx.kill_timestamp is None:
            return clip

        base_dur = float(getattr(clip, "duration", None) or ctx.clip_duration)
        dur = min(float(self.duration_sec), base_dur)
        center_t = float(ctx.kill_timestamp)
        start_t = max(0.0, center_t - dur * 0.4)
        end_t = min(base_dur, center_t + dur * 0.6)
        k_base = float(self.strength)
        # Cache remap grids keyed by (h, w) — rebuilt only if resolution changes.
        cache: dict[tuple[int, int, int], tuple[np.ndarray, np.ndarray]] = {}

        def maps_for(h: int, w: int, k_q: int) -> tuple[np.ndarray, np.ndarray]:
            key = (h, w, k_q)
            if key in cache:
                return cache[key]
            k = k_q / 1000.0
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            cx, cy = (w - 1) * 0.5, (h - 1) * 0.5
            dx = (xx - cx) / max(1.0, cx)
            dy = (yy - cy) / max(1.0, cy)
            r2 = dx * dx + dy * dy
            f = 1.0 + k * r2
            map_x = (cx + dx * f * cx).astype(np.float32)
            map_y = (cy + dy * f * cy).astype(np.float32)
            cache[key] = (map_x, map_y)
            return map_x, map_y

        def transform(get_frame, t: float):
            frame = get_frame(t)
            if t < start_t or t > end_t:
                return frame
            u = (float(t) - start_t) / max(1e-9, end_t - start_t)
            k = k_base * float(np.sin(np.pi * u))
            if k < 1e-4:
                return frame
            h, w = frame.shape[:2]
            map_x, map_y = maps_for(h, w, int(round(k * 1000)))
            return cv2.remap(frame, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

        return clip.transform(transform)
