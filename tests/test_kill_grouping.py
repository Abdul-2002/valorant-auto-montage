"""Multi-kill grouping: one clip per burst, no overlapping source footage."""

from __future__ import annotations

from src.ai.engine.kill_grouping import fit_groups_to_duration, group_kills, move_finale_last
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
