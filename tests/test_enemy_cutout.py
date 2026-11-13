"""Enemy cut-out mask validation: reject speckles / ground patches; accept solid center blobs."""

from __future__ import annotations

import numpy as np

from src.detection.enemy_cutout import (
    SAMPLE_OFFSETS_SEC,
    _CENTER_BOX_FRAC,
    refine_enemy_mask,
)


def _centered_blob(h: int = 200, w: int = 200, size: int = 28) -> np.ndarray:
    mask = np.zeros((h, w), dtype=bool)
    cy, cx = h // 2, w // 2
    half = size // 2
    mask[cy - half : cy + half, cx - half : cx + half] = True
    return mask


def test_should_accept_compact_centered_blob() -> None:
    out = refine_enemy_mask(_centered_blob())
    assert out is not None
    assert out.dtype == bool
    assert out.any()


def test_should_drop_speckles_and_reject_when_noise_dominates() -> None:
    """Large ground patch + dense dots — morph drops dots; keep-ratio fails."""
    h, w = 240, 240
    mask = np.zeros((h, w), dtype=bool)
    mask[105:125, 90:150] = True  # abrupt mid patch (~2% area)
    for y in range(20, 220):
        for x in range(20, 220):
            if (x + y) % 3 == 0:
                mask[y, x] = True

    assert refine_enemy_mask(mask) is None


def test_should_reject_elongated_abrupt_patch() -> None:
    mask = np.zeros((240, 240), dtype=bool)
    mask[110:124, 50:190] = True  # ~14x140 strip near center
    assert refine_enemy_mask(mask) is None


def test_should_reject_border_touching_mask() -> None:
    # Solid corridor from center blob to the top edge (survives morph open).
    mask = _centered_blob()
    mask[0:100, 86:114] = True
    assert refine_enemy_mask(mask) is None


def test_should_reject_huge_ground_patch() -> None:
    mask = np.zeros((200, 200), dtype=bool)
    mask[40:180, 20:180] = True
    assert refine_enemy_mask(mask) is None


def test_should_reject_off_center_blob() -> None:
    mask = np.zeros((200, 200), dtype=bool)
    mask[10:40, 10:40] = True
    assert refine_enemy_mask(mask) is None


def test_should_sample_earlier_and_use_tighter_box() -> None:
    assert SAMPLE_OFFSETS_SEC == (0.08, 0.16, 0.28)
    assert _CENTER_BOX_FRAC <= 0.055
