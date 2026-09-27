"""Beat planner: kills on strong beats, cuts on beats, plausible run-up speeds."""

from __future__ import annotations

from src.pipeline.beat_analyzer import BeatMap
from src.pipeline.beat_layout import (
    MULTI_KILL_SPEED_RANGE,
    PRE_BEATS_MAX,
    PRE_BEATS_MIN,
    ClipDemand,
    plan_kill_accents,
)

_INTERVAL = 0.5


def _backbeat_map(n: int = 400) -> BeatMap:
    beats = [i * _INTERVAL for i in range(n)]
    return BeatMap(
        tempo_bpm=120.0,
        beat_times=beats,
        onset_times=[],
        rms=[],
        sections=[],
        beat_strengths=[0.95 if i % 2 else 0.2 for i in range(n)],
    )


def test_should_put_kills_on_strong_beats_when_backbeat_exists() -> None:
    plans = plan_kill_accents(beat_map=_backbeat_map(), demands=[ClipDemand()] * 10, target_duration_sec=40)
    strengths = [s for p in plans for s in p.kill_strengths]
    assert len(plans) == 10
    assert sum(1 for s in strengths if s >= 0.9) >= 9


def test_should_cut_on_beats_and_keep_clips_contiguous() -> None:
    plans = plan_kill_accents(beat_map=_backbeat_map(), demands=[ClipDemand()] * 6, target_duration_sec=30)
    for a, b in zip(plans, plans[1:]):
        assert abs(a.output_end_sec - b.output_start_sec) < 1e-9
    for p in plans:
        assert abs((p.output_start_sec / _INTERVAL) - round(p.output_start_sec / _INTERVAL)) < 1e-9


def test_should_keep_run_up_between_min_and_max_beats() -> None:
    plans = plan_kill_accents(beat_map=_backbeat_map(), demands=[ClipDemand()] * 8, target_duration_sec=40)
    for p in plans:
        pre_beats = round((p.kill_output_sec[0] - p.output_start_sec) / _INTERVAL)
        assert PRE_BEATS_MIN <= pre_beats <= PRE_BEATS_MAX


def test_should_give_each_multi_kill_its_own_beat_at_plausible_speed() -> None:
    demand = ClipDemand(src_kill_gaps=(0.9, 1.4))
    plans = plan_kill_accents(beat_map=_backbeat_map(), demands=[demand], target_duration_sec=20)
    kills = plans[0].kill_output_sec
    assert len(kills) == 3
    lo, hi = MULTI_KILL_SPEED_RANGE
    for gap, (a, b) in zip(demand.src_kill_gaps, zip(kills, kills[1:])):
        assert lo <= gap / (b - a) <= hi


def test_should_use_synthetic_grid_when_no_music_is_given() -> None:
    plans = plan_kill_accents(beat_map=None, demands=[ClipDemand()] * 4, target_duration_sec=20)
    assert len(plans) == 4
    assert all(p.duration_sec >= 1.0 for p in plans)


def test_should_shorten_run_up_when_kill_is_at_video_start() -> None:
    plans = plan_kill_accents(
        beat_map=_backbeat_map(), demands=[ClipDemand(src_pre_available=0.6)], target_duration_sec=10
    )
    pre_beats = round((plans[0].kill_output_sec[0] - plans[0].output_start_sec) / _INTERVAL)
    assert pre_beats == 1
