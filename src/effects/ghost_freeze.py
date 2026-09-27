from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect
from src.effects.text_sprites import composite


def _with_outline(rgba: np.ndarray, rgb: tuple[int, int, int]) -> np.ndarray:
    """Add a soft glowing rim around the cut-out so the ghost reads against busy maps."""
    alpha = rgba[:, :, 3].astype(np.float32) / 255.0
    rim = cv2.dilate(alpha, np.ones((5, 5), np.uint8)) - alpha
    rim = np.clip(cv2.GaussianBlur(rim, (0, 0), 2.0) * 2.0, 0.0, 1.0)
    out = rgba.astype(np.float32)
    tint = np.asarray(rgb, dtype=np.float32)
    out[:, :, :3] = out[:, :, :3] * (1.0 - rim[..., None]) + tint * rim[..., None]
    out[:, :, 3] = np.maximum(out[:, :, 3], rim * 255.0)
    return out.astype(np.uint8)


@register_clip_effect("ghost_freeze")
@dataclass
class GhostFreezeEffect(ClipEffect):
    """Ghosted rotoscope freeze-frame: the enemy cut from the kill frame fades in ahead of the kill.

    The real enemy then steps into the exact spot and dies on the beat; the
    ghost vanishes on the kill frame.
    """

    enabled: bool = True
    cutout_path: str | None = None
    anchor_x: int = 0
    anchor_y: int = 0
    lead_sec: float = 0.5
    max_alpha: float = 0.55
    outline_rgb: tuple[int, int, int] = field(default_factory=lambda: (170, 230, 255))

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled or not self.cutout_path or ctx.kill_timestamp is None:
            return clip
        bgra = cv2.imread(str(self.cutout_path), cv2.IMREAD_UNCHANGED)
        if bgra is None or bgra.ndim != 3 or bgra.shape[2] != 4:
            return clip
        sprite = _with_outline(cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGBA), tuple(self.outline_rgb))
        kill_t = float(ctx.kill_timestamp)
        start_t = kill_t - float(self.lead_sec)
        cx = self.anchor_x + sprite.shape[1] / 2.0
        cy = self.anchor_y + sprite.shape[0] / 2.0

        def transform(get_frame, t: float):
            frame = get_frame(t)
            if not start_t <= t < kill_t:
                return frame
            u = (float(t) - start_t) / max(1e-6, float(self.lead_sec))
            alpha = float(self.max_alpha) * min(1.0, u * 3.0)
            return composite(frame, sprite, cx=cx, cy=cy, alpha=alpha)

        return clip.transform(transform)
