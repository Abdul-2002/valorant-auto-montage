"""Multi-kill grouping: one clip per burst, no overlapping source footage."""

from __future__ import annotations

from src.ai.engine.kill_grouping import (
    fit_groups_to_duration,
    group_kills,
    join_round_chains,
    move_finale_last,
    with_locked_finale,
)
from src.ai.enrichment import EnrichedEvent
from src.pipeline.types import DetectedEvent


def _ev(t: float, video: int = 0, score: float = 0.8) -> EnrichedEvent:
    return EnrichedEvent(
        event=DetectedEvent(video_index=video, timestamp_sec=t, score=score, event_type="kill"),
        video_duration_sec=300.0,
        gap_prev_sec=None,
        gap_next_sec=None,
        multi_kill_group_id=None,
    )


def test_should_merge_kills_within_burst_gap_into_one_group() -> None:
    groups = group_kills([_ev(10.0), _ev(11.5), _ev(13.0), _ev(30.0)])
    assert [len(g.events) for g in groups] == [3, 1]


def test_should_not_merge_kills_from_different_videos() -> None:
    groups = group_kills([_ev(10.0, video=0), _ev(10.5, video=1)])
    assert len(groups) == 2


def test_should_split_bursts_longer_than_max_kills() -> None:
    groups = group_kills([_ev(10.0 + i) for i in range(7)], max_kills=5)
    assert [len(g.events) for g in groups] == [5, 2]


def test_should_drop_weakest_single_kills_when_over_target() -> None:
    groups = group_kills([_ev(t, score=0.2 if t < 100 else 0.9) for t in (10, 40, 70, 100, 130, 160)])
    kept = fit_groups_to_duration(groups, target_sec=8.0, beat_interval=0.5)
    assert len(kept) == 4
    assert all(g.score == 0.9 for g in kept[1:])


def test_should_place_biggest_burst_last() -> None:
    groups = group_kills([_ev(10.0), _ev(11.0), _ev(12.0), _ev(50.0), _ev(90.0)])
    ordered = move_finale_last(groups)
    assert len(ordered[-1].events) == 3


def test_should_join_a_same_video_run_of_three_or_more_kills_within_eight_seconds() -> None:
    groups = join_round_chains(group_kills([_ev(t) for t in (10, 17, 21, 25, 28, 33)]))
    assert [len(g.events) for g in groups] == [6]


def test_should_leave_a_two_kill_pair_split_when_the_gap_exceeds_the_spray_window() -> None:
    groups = join_round_chains(group_kills([_ev(10.0), _ev(16.2)]))
    assert [len(g.events) for g in groups] == [1, 1]


def test_should_not_join_kills_when_the_gap_exceeds_eight_seconds() -> None:
    groups = join_round_chains(group_kills([_ev(10.0), _ev(22.0), _ev(26.0)]))
    assert [len(g.events) for g in groups] == [1, 1, 1]


def test_should_split_a_run_when_the_span_exceeds_twenty_eight_seconds() -> None:
    groups = join_round_chains(group_kills([_ev(t) for t in (0, 7, 14, 21, 29)]))
    assert [len(g.events) for g in groups] == [4, 1]


def test_should_not_join_round_chains_across_videos() -> None:
    groups = join_round_chains(
        group_kills([_ev(10, video=0), _ev(12, video=1), _ev(16, video=0), _ev(22, video=0)])
    )
    assert [(g.video_index, len(g.events)) for g in groups] == [(0, 3), (1, 1)]


def test_should_keep_the_biggest_spray_burst_last_when_a_round_is_joined() -> None:
    spray = group_kills([_ev(10), _ev(11), _ev(12), _ev(100), _ev(107), _ev(114), _ev(120)])
    ordered = with_locked_finale(spray)
    assert len(ordered[-1].events) == 3
    assert len(ordered[0].events) == 4


def test_should_assign_one_bar_to_a_weak_single_and_three_to_a_strong_single() -> None:
    weak = group_kills([_ev(10, score=0.4)])[0].demand()
    strong = group_kills([_ev(10, score=0.75)])[0].demand()
    assert weak.fixed_bars == 1 and weak.pre_beats == 3
    assert strong.fixed_bars == 3 and strong.pre_beats is None
