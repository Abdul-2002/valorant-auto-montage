"""Mask edge refine: hard binary masks must become soft alpha edges."""

from __future__ import annotations

import numpy as np

from src.cv.mask_refine import cleanup_mask, feather_mask_alpha


def test_should_produce_soft_edge_when_binary_mask_given() -> None:
    mask = np.zeros((64, 64), dtype=bool)
    mask[16:48, 16:48] = True

    alpha = feather_mask_alpha(mask, radius_px=4.0)

    assert alpha.dtype == np.float32
    assert alpha.shape == mask.shape
    assert float(alpha[32, 32]) >= 0.99
    assert float(alpha[0, 0]) == 0.0
    # Soft band just outside / on the hard edge must be partial, not binary.
    assert 0.05 < float(alpha[15, 32]) < 0.95
    assert 0.05 < float(alpha[16, 32]) < 0.99


def test_should_keep_empty_mask_zero() -> None:
    mask = np.zeros((16, 16), dtype=bool)
    alpha = feather_mask_alpha(mask, radius_px=3.0)
    assert float(alpha.max()) == 0.0


def test_should_reject_non_positive_radius() -> None:
    mask = np.ones((8, 8), dtype=bool)
    try:
        feather_mask_alpha(mask, radius_px=0.0)
    except ValueError:
        return
    raise AssertionError("expected ValueError for radius_px <= 0")


def test_should_keep_largest_component_when_speckles_present() -> None:
    mask = np.zeros((128, 128), dtype=bool)
    mask[40:90, 40:90] = True  # main blob
    mask[10, 10] = True
    mask[12, 15] = True
    mask[100, 110] = True
    mask[105:108, 20:23] = True  # tiny cluster

    cleaned = cleanup_mask(mask)

    assert cleaned.dtype == bool
    assert cleaned.shape == mask.shape
    # Morph close can expand a few pixels; require main blob kept and speckles gone.
    assert 2400 <= int(cleaned.sum()) <= 2700
    assert cleaned[65, 65]
    assert not cleaned[10, 10]
    assert not cleaned[105, 20]


def test_should_return_empty_when_mask_empty() -> None:
    cleaned = cleanup_mask(np.zeros((32, 32), dtype=bool))
    assert cleaned.shape == (32, 32)
    assert not cleaned.any()
