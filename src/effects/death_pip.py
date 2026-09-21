from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect


@register_clip_effect("death_pip")
@dataclass
class DeathPipEffect(ClipEffect):
    """Same-POV magnified inset after the kill (POV stand-in for a killcam)."""

    enabled: bool = True
    duration_sec: float = 0.95
    scale: float = 2.6
    size_frac: float = 0.36
    margin_frac: float = 0.025
    border_px: int = 5
    desaturate: float = 0.45

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled or ctx.kill_timestamp is None:
            return clip

        base_dur = float(getattr(clip, "duration", None) or ctx.clip_duration)
        dur = min(float(self.duration_sec), max(0.15, base_dur * 0.55))
        start_t = float(ctx.kill_timestamp)
        end_t = min(base_dur, start_t + dur)
        scale = float(self.scale)
        size_frac = float(self.size_frac)
        margin_frac = float(self.margin_frac)
        border = int(self.border_px)
        desat = float(self.desaturate)

        def transform(get_frame, t: float):
            frame = get_frame(t)
            if t < start_t or t > end_t:
                return frame
            h, w = frame.shape[:2]
            pip_w = max(48, int(w * size_frac))
            pip_h = max(48, int(h * size_frac))
            cw = max(16, int(w / scale))
            ch = max(16, int(h / scale))
            x0 = (w - cw) // 2
            y0 = (h - ch) // 2
            crop = frame[y0 : y0 + ch, x0 : x0 + cw]
            pip = cv2.resize(crop, (pip_w, pip_h), interpolation=cv2.INTER_LINEAR)
            if desat > 0.0:
                gray = cv2.cvtColor(pip, cv2.COLOR_RGB2GRAY)
                gray3 = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB).astype(np.float32)
                pip = np.clip(pip.astype(np.float32) * (1.0 - desat) + gray3 * desat, 0, 255).astype(np.uint8)
            if border > 0:
                pip = cv2.copyMakeBorder(
                    pip, border, border, border, border, cv2.BORDER_CONSTANT, value=(255, 220, 80)
                )
                pip_h, pip_w = pip.shape[:2]
            mx = int(w * margin_frac)
            my = int(h * margin_frac)
            x1 = w - pip_w - mx
            y1 = h - pip_h - my
            out = frame.copy()
            u = (float(t) - start_t) / max(1e-9, end_t - start_t)
            alpha = float(np.clip(min(u / 0.12, (1.0 - u) / 0.18, 1.0), 0.0, 1.0))
            roi = out[y1 : y1 + pip_h, x1 : x1 + pip_w].astype(np.float32)
            blended = roi * (1.0 - alpha) + pip.astype(np.float32) * alpha
            out[y1 : y1 + pip_h, x1 : x1 + pip_w] = np.clip(blended, 0, 255).astype(np.uint8)
            return out

        return clip.transform(transform)
