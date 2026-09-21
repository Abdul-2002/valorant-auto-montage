from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect


@register_clip_effect("light_wrap")
@dataclass
class LightWrapEffect(ClipEffect):
    """Soft radial brightness from screen center (crosshair) on the kill beat."""

    enabled: bool = True
    duration_sec: float = 0.4
    radius: float = 0.55
    intensity: float = 0.28

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled or ctx.kill_timestamp is None:
            return clip

        base_dur = float(getattr(clip, "duration", None) or ctx.clip_duration)
        dur = min(float(self.duration_sec), base_dur)
        center_t = float(ctx.kill_timestamp)
        start_t = max(0.0, center_t - dur * 0.35)
        end_t = min(base_dur, center_t + dur * 0.65)
        radius = float(self.radius)
        intensity = float(self.intensity)

        def transform(get_frame, t: float):
            frame = get_frame(t)
            if t < start_t or t > end_t:
                return frame
            u = (float(t) - start_t) / max(1e-9, end_t - start_t)
            fade = float(np.clip(1.0 - abs(2.0 * u - 1.0), 0.0, 1.0))
            h, w = frame.shape[:2]
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            dist = np.sqrt(((xx - w * 0.5) / (w * 0.5)) ** 2 + ((yy - h * 0.5) / (h * 0.5)) ** 2)
            falloff = np.clip(1.0 - dist / max(1e-6, radius), 0.0, 1.0) ** 1.6
            gain = 1.0 + intensity * fade * falloff
            out = frame.astype(np.float32) * gain[..., None]
            return np.clip(out, 0, 255).astype(np.uint8)

        return clip.transform(transform)
