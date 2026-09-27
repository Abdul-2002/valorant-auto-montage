"""Retime curve: kills pinned to beats, monotone time, post-kill slow-mo."""

from __future__ import annotations

import numpy as np

from src.pipeline.time_remap import build_clip_remap, make_remap_fn, slowmo_factor_for_source


def _remap(**overrides):
    params = dict(
        out_duration=3.0,
        kill_out=[1.2, 1.9],
        kill_src=[50.0, 50.8],
        src_bounds=(0.0, 300.0),
        approach_speed=1.15,
        slowmo_out=0.9,
        slowmo_factor=0.4,
        exit_speed=1.35,
    )
    params.update(overrides)
    return build_clip_remap(**params)


def test_should_land_every_kill_frame_on_its_beat_when_clip_is_a_multi_kill() -> None:
    remap = _remap()
    fn = make_remap_fn(remap.knots, src_max=remap.src_end_sec - remap.src_start_sec)
    for out_t, src_t in zip([1.2, 1.9], [50.0, 50.8]):
        assert abs(float(fn(out_t)) - (src_t - remap.src_start_sec)) < 1e-6


def test_should_never_run_source_time_backwards() -> None:
    remap = _remap()
    fn = make_remap_fn(remap.knots, src_max=1e9)
    src = fn(np.linspace(0.0, 3.0, 721))
    assert np.all(np.diff(src) > 0.0)


def test_should_slow_down_after_the_last_kill_not_before() -> None:
    remap = _remap(kill_out=[1.2], kill_src=[50.0])
    fn = make_remap_fn(remap.knots, src_max=1e9)
    before = (fn(1.2) - fn(0.9)) / 0.3
    after = (fn(1.2 + 0.06 + 0.8) - fn(1.2 + 0.06 + 0.1)) / 0.7
    assert before > 0.9
    assert 0.3 < after < 0.5


def test_should_start_source_window_at_approach_speed_before_first_kill() -> None:
    remap = _remap(kill_out=[1.2], kill_src=[50.0])
    assert abs(remap.src_start_sec - (50.0 - 1.2 * 1.15)) < 1e-6


def test_should_cap_slowmo_at_half_speed_when_source_is_60fps() -> None:
    assert slowmo_factor_for_source(target=0.4, source_fps=60.0, min_unique_fps=30.0) == 0.5
    assert slowmo_factor_for_source(target=0.4, source_fps=120.0, min_unique_fps=30.0) == 0.4


def test_should_stay_monotonic_when_kill_is_near_end_of_video() -> None:
    remap = _remap(kill_out=[1.2], kill_src=[299.8], src_bounds=(0.0, 300.0))
    fn = make_remap_fn(remap.knots, src_max=1e9)
    src = fn(np.linspace(0.0, 3.0, 181))
    assert np.all(np.diff(src) > 0.0)


def test_should_skip_slowmo_when_recipe_has_none() -> None:
    remap = _remap(kill_out=[1.2], kill_src=[50.0], slowmo_out=0.0)
    assert len(remap.knots) == 3
