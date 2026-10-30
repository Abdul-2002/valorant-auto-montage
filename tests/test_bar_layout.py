"""Bar allocation: kill-only clips stay one bar, and leftover song does not pad the finale."""

from __future__ import annotations

from src.pipeline.bar_layout import plan_on_bars
from src.pipeline.beat_analyzer import BeatMap, BeatSection
from src.pipeline.beat_layout import ClipDemand

_INTERVAL = 0.5


def _bar_map(n_bars: int = 20) -> BeatMap:
    beats = [i * _INTERVAL for i in range(n_bars * 4 + 1)]
    return BeatMap(
        tempo_bpm=120.0,
        beat_times=beats,
        onset_times=[],
        rms=[],
        sections=[],
        beat_strengths=[0.9] * len(beats),
        downbeat_times=beats[::4],
    )


def test_should_keep_a_weak_single_at_one_bar_and_not_stretch_the_finale() -> None:
    plans = plan_on_bars(
        beat_map=_bar_map(),
        demands=[
            ClipDemand(fixed_bars=1, pre_beats=2),
            ClipDemand(fixed_bars=3),
            ClipDemand(src_kill_gaps=(1.0, 1.0)),
        ],
        song_end_sec=40.0,
    )
    assert len(plans) == 3
    assert abs(plans[0].duration_sec - 2.0) < 1e-6
    assert abs(plans[0].kill_output_sec[0] - plans[0].output_start_sec - 1.0) < 1e-6
    assert abs(plans[1].duration_sec - 6.0) < 1e-6
    assert plans[2].duration_sec <= 12.0
    assert plans[2].output_end_sec < 40.0


def test_should_keep_origin_at_zero_when_bed_opens_on_intro() -> None:
    beats = [i * _INTERVAL for i in range(81)]
    beat_map = BeatMap(
        tempo_bpm=120.0,
        beat_times=beats,
        onset_times=[],
        rms=[],
        sections=[
            BeatSection(0.0, 8.0, "intro", 0.3),
            BeatSection(8.0, 16.0, "verse", 0.4),
            BeatSection(16.0, 40.0, "chorus", 0.8),
        ],
        beat_strengths=[0.9] * len(beats),
        downbeat_times=beats[::4],
    )
    plans = plan_on_bars(
        beat_map=beat_map,
        demands=[
            ClipDemand(fixed_bars=1, pre_beats=2),
            ClipDemand(fixed_bars=1, pre_beats=2),
            ClipDemand(src_kill_gaps=(1.0, 1.0, 1.0), fixed_bars=4),
            ClipDemand(src_kill_gaps=(1.0,), fixed_bars=2),
        ],
        song_end_sec=40.0,
    )
    assert plans
    assert abs(plans[0].output_start_sec - 0.0) < 1e-6


def test_should_open_the_longest_run_on_the_first_chorus() -> None:
    beats = [i * _INTERVAL for i in range(81)]
    beat_map = BeatMap(
        tempo_bpm=120.0,
        beat_times=beats,
        onset_times=[],
        rms=[],
        sections=[
            BeatSection(0.0, 16.0, "verse", 0.4),
            BeatSection(16.0, 40.0, "chorus", 0.8),
        ],
        beat_strengths=[0.9] * len(beats),
        downbeat_times=beats[::4],
    )
    plans = plan_on_bars(
        beat_map=beat_map,
        demands=[
            ClipDemand(fixed_bars=1, pre_beats=2),
            ClipDemand(fixed_bars=1, pre_beats=2),
            ClipDemand(src_kill_gaps=(1.0, 1.0, 1.0), fixed_bars=4),
            ClipDemand(src_kill_gaps=(1.0,), fixed_bars=2),
        ],
        song_end_sec=40.0,
    )
    assert len(plans) == 4
    assert abs(plans[2].output_start_sec - 16.0) < 1e-6
    assert plans[2].output_start_sec > plans[1].output_end_sec - 1e-6
