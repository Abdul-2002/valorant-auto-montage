"""Detect a scoped sniper view (Operator / Marshal / Outlaw) from raw POV frames.

Scoped views render a circular lens with black fill on both sides; normal ADS
and hip-fire never blacken the mid-left and mid-right screen bands, and the
HUD (minimap, killfeed, abilities) does not sit there either.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np

log = logging.getLogger(__name__)

_DARK_LEVEL = 32
_DARK_FRACTION = 0.85
_CENTER_MIN_LUMA = 35.0
# Sample just before the kill: the unscope happens right after the shot.
_SAMPLE_OFFSETS_SEC: tuple[float, ...] = (0.05, 0.15, 0.3)


def _band_dark_fraction(band: np.ndarray) -> float:
    if band.size == 0:
        return 0.0
    return float((band.max(axis=2) < _DARK_LEVEL).mean())


def is_scoped_frame(frame_bgr: np.ndarray) -> bool:
    """True when both side bands are near-black while the lens center is lit."""
    h, w = frame_bgr.shape[:2]
    y0, y1 = int(0.40 * h), int(0.60 * h)
    left = frame_bgr[y0:y1, int(0.02 * w) : int(0.14 * w)]
    right = frame_bgr[y0:y1, int(0.86 * w) : int(0.98 * w)]
    if _band_dark_fraction(left) < _DARK_FRACTION or _band_dark_fraction(right) < _DARK_FRACTION:
        return False
    center = frame_bgr[y0:y1, int(0.40 * w) : int(0.60 * w)]
    return float(cv2.cvtColor(center, cv2.COLOR_BGR2GRAY).mean()) >= _CENTER_MIN_LUMA


def detect_scoped_before_kills(video_path: Path, kill_secs: Sequence[float]) -> list[bool]:
    """Per kill timestamp: was the player scoped in during the frames before the kill."""
    results = [False] * len(kill_secs)
    if not kill_secs:
        return results
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        log.warning("scope_state: cannot open %s; treating all kills as unscoped", video_path)
        return results
    try:
        for i, kill_sec in enumerate(kill_secs):
            for offset in _SAMPLE_OFFSETS_SEC:
                cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(kill_sec) - offset) * 1000.0)
                ok, frame = cap.read()
                if ok and frame is not None and is_scoped_frame(frame):
                    results[i] = True
                    break
    finally:
        cap.release()
    return results
