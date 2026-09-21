"""Duration-preserving transition stylers used by the montage assembler.

These mutate only the tail of clip A and/or head of clip B so the output
timeline length (and therefore beat sync) is unchanged.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def _window_alpha(t: float, start: float, end: float) -> float:
    if end <= start or t < start or t > end:
        return 0.0
    u = (t - start) / (end - start)
    return float(np.sin(np.pi * u))


def style_whip_tail(clip: Any, *, duration_sec: float, blur_px: int = 36) -> Any:
    """Horizontal motion blur + slide on the last ``duration_sec`` of a clip."""
    base_dur = float(getattr(clip, "duration", 0.0) or 0.0)
    d = min(max(0.05, float(duration_sec)), max(0.05, base_dur * 0.45))
    start = max(0.0, base_dur - d)
    amount = max(2, int(blur_px))

    def transform(get_frame, t):
        frame = get_frame(t)
        a = _window_alpha(float(t), start, base_dur)
        if a <= 0.0:
            return frame
        k = max(1, int(round(amount * a)))
        kernel = np.zeros((1, k), dtype=np.float32)
        kernel[0, :] = 1.0 / k
        blurred = cv2.filter2D(frame, -1, kernel)
        shift = int(round(frame.shape[1] * 0.08 * a))
        if shift:
            blurred = np.roll(blurred, -shift, axis=1)
            blurred[:, -shift:] = 0
        return blurred

    return clip.transform(transform)


def style_whip_head(clip: Any, *, duration_sec: float, blur_px: int = 36) -> Any:
    """Incoming whip on the head of the next clip."""
    base_dur = float(getattr(clip, "duration", 0.0) or 0.0)
    d = min(max(0.05, float(duration_sec)), max(0.05, base_dur * 0.45))
    amount = max(2, int(blur_px))

    def transform(get_frame, t):
        frame = get_frame(t)
        a = _window_alpha(float(t), 0.0, d)
        if a <= 0.0:
            return frame
        k = max(1, int(round(amount * a)))
        kernel = np.zeros((1, k), dtype=np.float32)
        kernel[0, :] = 1.0 / k
        blurred = cv2.filter2D(frame, -1, kernel)
        shift = int(round(frame.shape[1] * 0.08 * a))
        if shift:
            blurred = np.roll(blurred, shift, axis=1)
            blurred[:, :shift] = 0
        return blurred

    return clip.transform(transform)


def style_push_head(clip: Any, *, duration_sec: float) -> Any:
    """Slide the next clip in from the right over its first ``duration_sec``."""
    base_dur = float(getattr(clip, "duration", 0.0) or 0.0)
    d = min(max(0.05, float(duration_sec)), max(0.05, base_dur * 0.4))

    def transform(get_frame, t):
        frame = get_frame(t)
        if float(t) > d:
            return frame
        u = float(t) / d
        shift = int(round(frame.shape[1] * (1.0 - u)))
        if shift <= 0:
            return frame
        out = np.zeros_like(frame)
        out[:, shift:] = frame[:, : frame.shape[1] - shift]
        return out

    return clip.transform(transform)
