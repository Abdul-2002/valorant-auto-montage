from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect


@register_clip_effect("impact_stylize")
@dataclass
class ImpactStylizeEffect(ClipEffect):
    """Zishu-style find-edges + warm glow pulse around the kill."""

    enabled: bool = True
    duration_sec: float = 0.45
    edge_strength: float = 0.55
    glow_strength: float = 0.35
    brightness_pulse: float = 0.12

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled or ctx.kill_timestamp is None:
            return clip

        base_dur = float(getattr(clip, "duration", None) or ctx.clip_duration)
        dur = min(float(self.duration_sec), base_dur)
        center_t = float(ctx.kill_timestamp)
        start_t = max(0.0, center_t - dur * 0.25)
        end_t = min(base_dur, center_t + dur * 0.75)
        edge_s = float(self.edge_strength)
        glow_s = float(self.glow_strength)
        bright = float(self.brightness_pulse)

        def transform(get_frame, t: float):
            frame = get_frame(t)
            if t < start_t or t > end_t:
                return frame
            u = (float(t) - start_t) / max(1e-9, end_t - start_t)
            fade = float(np.clip(1.0 - abs(2.0 * u - 1.0), 0.0, 1.0))
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            edges = cv2.Canny(gray, 80, 160)
            edges_rgb = cv2.cvtColor(edges, cv2.COLOR_GRAY2RGB).astype(np.float32)
            # Warm tritone-ish cast on edges.
            edges_rgb[:, :, 0] *= 1.15
            edges_rgb[:, :, 1] *= 0.85
            edges_rgb[:, :, 2] *= 0.55
            base = frame.astype(np.float32)
            glow = cv2.GaussianBlur(base, (0, 0), 3.0)
            out = base * (1.0 + bright * fade)
            out = out * (1.0 - edge_s * fade) + edges_rgb * (edge_s * fade)
            out = out * (1.0 - glow_s * fade * 0.5) + glow * (glow_s * fade * 0.5)
            return np.clip(out, 0, 255).astype(np.uint8)

        return clip.transform(transform)
