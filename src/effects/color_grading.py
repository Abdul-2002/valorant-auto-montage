from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect


@register_clip_effect("color_grading")
@dataclass
class ColorGradingEffect(ClipEffect):
    enabled: bool = True
    saturation: float = 1.3
    contrast: float = 1.1
    brightness: float = 0.02
    lut_file: str | None = None

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled:
            return clip

        def transform(get_frame, t: float):
            frame = get_frame(t)
            img = frame.astype(np.float32) / 255.0
            img = (img - 0.5) * self.contrast + 0.5 + self.brightness
            img = np.clip(img, 0.0, 1.0)

            hsv = cv2.cvtColor((img * 255).astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
            hsv[:, :, 1] *= self.saturation
            hsv[:, :, 1] = np.clip(hsv[:, :, 1], 0, 255)
            out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)
            return out

        return clip.transform(transform)
