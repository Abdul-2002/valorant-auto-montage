from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.envelopes import decay_envelope
from src.effects.highlight_bloom import bright_pass_glow, screen_add
from src.effects.registry import register_clip_effect

HIT_STYLES: tuple[str, ...] = ("flash_blur", "glow", "flash_shake")
_REFERENCE_HEIGHT = 1080.0


def _lens_blur(img: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian stand-in for camera lens blur, computed at half resolution for speed."""
    if sigma < 0.6:
        return img
    h, w = img.shape[:2]
    small = cv2.resize(img, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), sigma / 2.0)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


@register_clip_effect("kill_hit")
@dataclass
class KillHitEffect(ClipEffect):
    """Beat-synced hit on every kill frame; later kills of a burst hit hardest."""

    enabled: bool = True
    style: str = "flash_blur"
    decay_sec: float = 0.3
    flash_strength: float = 0.5
    blur_px: float = 16.0
    glow_threshold: float = 0.55
    glow_blur_px: int = 31
    glow_intensity: float = 1.2
    minor_scale: float = 0.6

    def _strength(self, t: float, anchors: tuple[float, ...]) -> float:
        scales = [float(self.minor_scale)] * (len(anchors) - 1) + [1.0]
        return max(s * decay_envelope(t, a, float(self.decay_sec)) for s, a in zip(scales, anchors))

    def _hit(self, frame: np.ndarray, e: float) -> np.ndarray:
        img = frame.astype(np.float32) / 255.0
        scale = frame.shape[0] / _REFERENCE_HEIGHT
        flash = float(self.flash_strength) * e
        if self.style == "glow":
            blur = int(round(float(self.glow_blur_px) * scale))
            glow = bright_pass_glow(img, threshold=float(self.glow_threshold), blur_px=blur, weapon_bias=0.2)
            img = screen_add(img, glow, float(self.glow_intensity) * e)
            flash *= 0.35
        elif self.style == "flash_blur":
            # blur_px is a lens-blur radius; Gaussian sigma ~ radius / 2.
            img = _lens_blur(img, 0.5 * float(self.blur_px) * scale * e)
        elif self.style == "flash_shake":
            # The camera effect carries the (boosted) shake; the hit is a harder flash.
            flash = min(1.0, flash * 1.3)
        img = img + (1.0 - img) * flash
        return (np.clip(img, 0.0, 1.0) * 255.0).astype(np.uint8)

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        anchors = tuple(float(a) for a in ctx.kill_timestamps) or (
            (float(ctx.kill_timestamp),) if ctx.kill_timestamp is not None else ()
        )
        if not self.enabled or not anchors:
            return clip

        def transform(get_frame, t: float):
            frame = get_frame(t)
            e = self._strength(float(t), anchors)
            if e < 0.01:
                return frame
            return self._hit(frame, e)

        return clip.transform(transform)
