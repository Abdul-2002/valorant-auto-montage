"""Scoped-view detection used to gate the scope mask effect."""

from __future__ import annotations

import cv2
import numpy as np

from src.detection.scope_state import is_scoped_frame


def _scoped_frame(h: int = 720, w: int = 1280) -> np.ndarray:
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.circle(frame, (w // 2, h // 2), int(h * 0.47), (120, 140, 150), thickness=-1)
    return frame


def test_should_detect_scope_when_side_bands_are_black_and_lens_is_lit() -> None:
    assert is_scoped_frame(_scoped_frame()) is True


def test_should_not_detect_scope_on_normal_gameplay() -> None:
    frame = np.full((720, 1280, 3), 90, dtype=np.uint8)
    assert is_scoped_frame(frame) is False


def test_should_not_detect_scope_on_fully_black_frame() -> None:
    assert is_scoped_frame(np.zeros((720, 1280, 3), dtype=np.uint8)) is False


def test_should_not_detect_scope_when_only_one_side_is_dark() -> None:
    frame = np.full((720, 1280, 3), 90, dtype=np.uint8)
    frame[:, :200] = 0
    assert is_scoped_frame(frame) is False
