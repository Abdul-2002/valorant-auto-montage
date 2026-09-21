from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect


@register_clip_effect("scope_vignette")
@dataclass
class ScopeVignetteEffect(ClipEffect):
    enabled: bool = True
    duration_sec: float = 0.55
    inner_radius: float = 0.28
    darkness: float = 0.88
    flash_scope: bool = True

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled or ctx.kill_timestamp is None:
            return clip

        base_dur = float(getattr(clip, "duration", None) or ctx.clip_duration)
        dur = min(float(self.duration_sec), base_dur)
        center_t = float(ctx.kill_timestamp)
        start_t = max(0.0, center_t - dur * 0.55)
        end_t = min(base_dur, center_t + dur * 0.45)
        dark = float(self.darkness)
        r0 = float(self.inner_radius)
        do_flash = bool(self.flash_scope)

        def transform(get_frame, t: float):
            frame = get_frame(t)
            if t < start_t or t > end_t:
                return frame
            h, w = frame.shape[:2]
            u = (float(t) - start_t) / max(1e-9, end_t - start_t)
            # Flash-scope: radius starts large and snaps inward toward the kill.
            if do_flash:
                radius = r0 + (0.75 - r0) * max(0.0, 1.0 - min(1.0, u / 0.35))
            else:
                radius = r0
            strength = dark * (1.0 - abs(2.0 * u - 1.0))
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            dist = np.sqrt(((xx - w * 0.5) / (w * 0.5)) ** 2 + ((yy - h * 0.5) / (h * 0.5)) ** 2)
            mask = np.clip((dist - radius) / max(1e-6, 1.0 - radius), 0.0, 1.0)
            mask = (mask * strength)[..., None]
            out = frame.astype(np.float32) * (1.0 - mask)
            return np.clip(out, 0, 255).astype(np.uint8)

        return clip.transform(transform)
