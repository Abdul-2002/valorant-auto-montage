from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.envelopes import hold_fade_envelope
from src.effects.highlight_bloom import bright_pass_glow, screen_add
from src.effects.registry import register_clip_effect

_REFERENCE_HEIGHT = 1080.0


def edge_map(frame_rgb: np.ndarray) -> np.ndarray:
    """Inverted find-edges: bright lines on black, normalized to 0..1."""
    gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    mag = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))
    ref = float(np.percentile(mag[::4, ::4], 99.0))
    return np.clip(mag / max(ref, 1e-6), 0.0, 1.0)


def tritone(edges: np.ndarray, mid_rgb: np.ndarray, high_rgb: np.ndarray) -> np.ndarray:
    """Map edge intensity to black -> mid hue -> highlight hue (single-color lines)."""
    e = edges[..., None]
    lower = mid_rgb * np.clip(e * 2.0, 0.0, 1.0)
    upper = (high_rgb - mid_rgb) * np.clip(e * 2.0 - 1.0, 0.0, 1.0)
    return np.clip((lower + upper) / 255.0, 0.0, 1.0)


@register_clip_effect("edge_glow")
@dataclass
class EdgeGlowEffect(ClipEffect):
    """Zishu kill stylize: find-edges + single-hue tritone + glow, then blend back to footage."""

    enabled: bool = True
    hold_sec: float = 0.1
    fade_sec: float = 0.5
    mid_rgb: tuple[int, int, int] = field(default_factory=lambda: (40, 140, 255))
    highlight_rgb: tuple[int, int, int] = field(default_factory=lambda: (210, 240, 255))
    glow_threshold: float = 0.3
    glow_blur_px: int = 51
    glow_intensity: float = 1.0

    def _stylize(self, frame: np.ndarray) -> np.ndarray:
        mid = np.asarray(self.mid_rgb, dtype=np.float32)
        high = np.asarray(self.highlight_rgb, dtype=np.float32)
        lines = tritone(edge_map(frame), mid, high)
        blur = int(round(float(self.glow_blur_px) * frame.shape[0] / _REFERENCE_HEIGHT))
        glow = bright_pass_glow(lines, threshold=float(self.glow_threshold), blur_px=blur, weapon_bias=0.0)
        return screen_add(lines, glow, float(self.glow_intensity))

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled or ctx.kill_timestamp is None:
            return clip
        anchor = float(ctx.kill_timestamp)

        def transform(get_frame, t: float):
            frame = get_frame(t)
            w = hold_fade_envelope(float(t), anchor, float(self.hold_sec), float(self.fade_sec))
            if w < 0.01:
                return frame
            styl = self._stylize(frame)
            out = frame.astype(np.float32) / 255.0 * (1.0 - w) + styl * w
            return (np.clip(out, 0.0, 1.0) * 255.0).astype(np.uint8)

        return clip.transform(transform)
