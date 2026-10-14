"""Gun outline: mask validation gating, budget assignment, and the draw core."""

from __future__ import annotations

import numpy as np

from src.ai.engine.feature_budget import MAX_GUN_OUTLINES, assign_features
from src.effects.gun_outline import (
    GunOutlineEffect,
    draw_outline,
    out_rel_to_src_offset,
    warp_contours_with_flow,
)
from src.pipeline.weapon_assets import _contours_of, clean_weapon_mask, valid_weapon_mask


def _mask(*, x0: int, x1: int, y0: int, y1: int, shape: tuple[int, int] = (1080, 1920)) -> np.ndarray:
    mask = np.zeros(shape, dtype=bool)
    mask[y0:y1, x0:x1] = True
    return mask


def test_should_accept_wide_bottom_half_weapon_mask() -> None:
    # ~2.6% of frame, aspect ~2.2, centroid at 0.79h.
    assert valid_weapon_mask(_mask(x0=1000, x1=1420, y0=800, y1=990))


def test_should_reject_tiny_huge_vertical_and_top_half_masks() -> None:
    assert not valid_weapon_mask(_mask(x0=1000, x1=1030, y0=900, y1=930))  # tiny
    assert not valid_weapon_mask(_mask(x0=200, x1=1700, y0=300, y1=1000))  # huge
    assert not valid_weapon_mask(_mask(x0=1100, x1=1200, y0=600, y1=1000))  # vertical arm
    assert not valid_weapon_mask(_mask(x0=1000, x1=1400, y0=100, y1=280))  # top half


def test_should_budget_gun_outlines_on_slow_and_cinematic_only() -> None:
    n = 12
    recipes = ["clean"] + ["slow"] * (n - 2) + ["cinematic"]
    features = assign_features(recipes=recipes, kill_counts=[1] * n, scores=[0.4 + i * 0.04 for i in range(n)])
    guns = [i for i, f in enumerate(features) if f.gun_candidate]
    assert 1 <= len(guns) <= MAX_GUN_OUTLINES
    assert all(recipes[i] in ("slow", "cinematic") for i in guns)
    assert 0 not in guns  # intro clip keeps the title clean
    assert all(abs(a - b) > 1 for i, a in enumerate(guns) for b in guns[i + 1 :])


def test_should_not_budget_guns_on_clean_or_punch_clips() -> None:
    features = assign_features(recipes=["clean", "punch", "clean"], kill_counts=[1, 1, 1], scores=[0.9, 0.8, 0.7])
    assert all(not f.gun_candidate for f in features)


def test_should_draw_glowing_contour_inside_window_only() -> None:
    frame = np.zeros((200, 300, 3), dtype=np.uint8)
    contour = np.array([[[150, 120]], [[260, 120]], [[260, 170]], [[150, 170]]], dtype=np.int32)
    out = draw_outline(frame, (contour,), color=(90, 220, 255), thickness=3, glow_blur_px=15, alpha=1.0)
    assert out[120, 200].sum() > 400  # on the contour
    assert out[60, 60].sum() == 0  # far from the contour
    assert draw_outline(frame, (contour,), color=(90, 220, 255), thickness=3, glow_blur_px=15, alpha=0.0).sum() == 0


def test_should_modulate_alpha_around_the_kill() -> None:
    eff = GunOutlineEffect(enabled=True, asset_path="x.json", pre_sec=0.1, window_sec=0.6, max_alpha=0.9)
    assert eff._alpha(0.89, 1.0) == 0.0  # before the ramp (start = kill - pre_sec)
    assert abs(eff._alpha(0.95, 1.0) - 0.45) < 1e-9  # mid-ramp
    assert eff._alpha(1.0, 1.0) == 0.9  # on the kill
    assert eff._alpha(1.2, 1.0) == 0.9  # hold
    assert eff._alpha(1.61, 1.0) == 0.0  # after the window


def test_should_drop_tiny_island_contours_after_cleanup() -> None:
    mask = _mask(x0=1000, x1=1420, y0=800, y1=990)
    # Speckle island that used to survive findContours.
    mask[820:828, 1600:1608] = True
    cleaned = clean_weapon_mask(mask)
    assert cleaned is not None
    contours = _contours_of(cleaned)
    assert len(contours) == 1


def test_should_map_output_time_through_slowmo_and_warp_by_flow() -> None:
    assert abs(out_rel_to_src_offset(0.9, 0.4) - 0.36) < 1e-9
    assert out_rel_to_src_offset(-0.1, 0.4) == -0.1
    contour = np.array([[[100, 100]], [[120, 100]], [[120, 120]], [[100, 120]]], dtype=np.int32)
    flow = np.zeros((200, 200, 2), dtype=np.float32)
    flow[..., 0] = 10.0
    flow[..., 1] = -5.0
    warped = warp_contours_with_flow((contour,), flow)[0].reshape(-1, 2)
    assert warped[0, 0] == 110
    assert warped[0, 1] == 95
