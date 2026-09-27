"""Death-cam / spectator rejection for kill-skull refinement."""

from __future__ import annotations

import numpy as np

from src.detection.kill_frame_refine import is_death_or_spectator_frame, kill_skull_score


def test_death_cam_frame_rejects_skull() -> None:
    # Synthetic death-cam: dark bottom-left plate + white glyphs, dark right panel.
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame[:] = (40, 40, 40)
    # SWITCH PLAYER band
    frame[int(0.82 * 720) : int(0.98 * 720), int(0.02 * 1280) : int(0.28 * 1280)] = (20, 20, 20)
    frame[int(0.86 * 720) : int(0.92 * 720), int(0.04 * 1280) : int(0.22 * 1280)] = (230, 230, 230)
    # Combat report panel
    frame[int(0.15 * 720) : int(0.70 * 720), int(0.68 * 1280) : int(0.96 * 1280)] = (25, 25, 25)
    frame[int(0.20 * 720) : int(0.35 * 720), int(0.72 * 1280) : int(0.90 * 1280)] = (220, 220, 220)

    assert is_death_or_spectator_frame(frame) is True
    assert kill_skull_score(frame) == 0.0


def test_live_pov_is_not_death_cam() -> None:
    frame = np.full((720, 1280, 3), 90, dtype=np.uint8)
    # Mild killfeed top-right (should not trip death-cam).
    frame[20:80, 1000:1260] = (200, 200, 200)
    assert is_death_or_spectator_frame(frame) is False
