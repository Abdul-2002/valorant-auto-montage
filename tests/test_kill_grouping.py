"""Multi-kill grouping: one clip per burst, no overlapping source footage."""

from __future__ import annotations

from src.ai.engine.kill_grouping import (
    build_play_flows,
    curate_plays,
    fit_groups_to_duration,
    group_kills,
    join_round_chains,
    move_finale_last,
    with_locked_finale,
)
from src.ai.enrichment import EnrichedEvent
from src.pipeline.types import DetectedEvent


def _ev(
    t: float,
    video: int = 0,
    score: float = 0.8,
    *,
    event_type: str = "kill",
    scoped: bool = False,
) -> EnrichedEvent:
    return EnrichedEvent(
        event=DetectedEvent(video_index=video, timestamp_sec=t, score=score, event_type=event_type),
        video_duration_sec=300.0,
        gap_prev_sec=None,
        gap_next_sec=None,
        multi_kill_group_id=None,
        scoped=scoped,
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


def test_should_join_a_same_video_run_of_kills_within_the_round_window() -> None:
    groups = join_round_chains(group_kills([_ev(t) for t in (10, 17, 21, 25, 28, 33)]))
    assert [len(g.events) for g in groups] == [6]


def test_should_keep_n_kills_in_one_clip_when_fired_back_to_back() -> None:
    times = [10.0, 12.0, 14.5, 17.0, 19.5, 22.0]
    groups = join_round_chains(group_kills([_ev(t) for t in times]))
    assert len(groups) == 1
    assert len(groups[0].events) == 6


def test_should_keep_a_double_as_one_clip_when_gap_is_inside_the_round_window() -> None:
    groups = join_round_chains(group_kills([_ev(10.0), _ev(16.2)]))
    assert [len(g.events) for g in groups] == [2]


def test_should_not_join_kills_when_the_gap_exceeds_the_round_window() -> None:
    groups = join_round_chains(group_kills([_ev(10.0), _ev(25.0), _ev(29.0)]))
    assert [len(g.events) for g in groups] == [1, 2]


def test_should_split_a_run_when_the_span_exceeds_the_round_span() -> None:
    # 0→48 spans > 45s → first chain stops before the last frag.
    groups = join_round_chains(group_kills([_ev(t) for t in (0, 10, 20, 30, 48)]))
    assert sum(len(g.events) for g in groups) == 5
    assert max(len(g.events) for g in groups) >= 2
    assert len(groups) >= 2


def test_should_not_join_round_chains_across_videos() -> None:
    groups = join_round_chains(
        group_kills([_ev(10, video=0), _ev(12, video=1), _ev(16, video=0), _ev(22, video=0)])
    )
    assert [(g.video_index, len(g.events)) for g in groups] == [(0, 3), (1, 1)]


def test_should_keep_the_biggest_round_flow_last_after_chaining() -> None:
    # Tight 3-spray + spaced 4-kill round. Chain first, then lock the 4-kill as finale.
    spray = group_kills([_ev(10), _ev(11), _ev(12), _ev(100), _ev(107), _ev(114), _ev(120)])
    ordered = with_locked_finale(spray)
    assert len(ordered[-1].events) == 4
    assert len(ordered[0].events) == 3


def test_should_keep_an_ace_as_one_continuous_flow_when_gaps_are_a_few_seconds() -> None:
    # Typical ace timing: 3–6s between frags — too wide for the spray window alone.
    events = [_ev(t, score=0.9) for t in (10.0, 14.0, 18.5, 23.0, 27.5)]
    singles = [_ev(t, score=0.5) for t in (80.0, 100.0, 120.0)]
    ordered = with_locked_finale(build_play_flows(events + singles))
    assert len(ordered[-1].events) == 5
    assert [round(t, 1) for t in ordered[-1].kill_secs] == [10.0, 14.0, 18.5, 23.0, 27.5]


def test_should_drop_singles_before_breaking_a_multi_kill_when_over_budget() -> None:
    ace = [_ev(t, score=0.95) for t in (10.0, 14.0, 18.0, 22.0, 26.0)]
    filler = [_ev(t, score=0.4) for t in (50.0, 70.0, 90.0, 110.0, 130.0)]
    plays = build_play_flows(ace + filler)
    kept = fit_groups_to_duration(plays, target_sec=12.0, beat_interval=0.5)
    assert any(len(g.events) == 5 for g in kept)
    assert all(len(g.events) >= 1 for g in kept)


def test_should_assign_one_bar_to_a_weak_single_and_three_to_a_strong_single() -> None:
    weak = group_kills([_ev(10, score=0.4)])[0].demand()
    strong = group_kills([_ev(10, score=0.75)])[0].demand()
    assert weak.fixed_bars == 1 and weak.pre_beats == 3
    assert strong.fixed_bars == 2 and strong.pre_beats is None


def test_should_drop_low_score_filler_singles_even_when_the_bed_has_room() -> None:
    ace = [_ev(t, score=0.95) for t in (10.0, 14.0, 18.0, 22.0, 26.0)]
    filler = [_ev(t, score=0.45) for t in (50.0, 70.0, 90.0, 110.0)]
    strong = [_ev(t, score=0.8) for t in (130.0, 150.0)]
    kept = curate_plays(build_play_flows(ace + filler + strong), target_sec=120.0, beat_interval=0.5)
    assert any(len(g.events) == 5 for g in kept)
    assert all(g.score >= 0.62 or len(g.events) >= 2 for g in kept)


def test_should_prefer_headshot_single_over_plain_single_of_equal_score() -> None:
    plain = _ev(10.0, score=0.7, event_type="kill")
    hs = _ev(40.0, score=0.7, event_type="headshot")
    ordered = with_locked_finale(build_play_flows([plain, hs]))
    assert ordered[-1].has_headshot


def test_should_prefer_gemini_ace_label_over_higher_score_single() -> None:
    from src.ai.engine.kill_grouping import KillGroup

    weak_ace = KillGroup(events=(_ev(10.0, score=0.55), _ev(14.0, score=0.55), _ev(18.0, score=0.55)), play_label="ace")
    loud = KillGroup(events=(_ev(50.0, score=0.95),), play_label="clean")
    ordered = with_locked_finale([loud, weak_ace])
    assert ordered[-1].play_label == "ace"


def test_should_drop_gemini_junk_singles_in_curate() -> None:
    from src.ai.engine.kill_grouping import KillGroup

    good = KillGroup(events=(_ev(10.0, score=0.8),), play_label="headshot")
    junk = KillGroup(events=(_ev(40.0, score=0.9),), play_label="junk")
    kept = curate_plays([good, junk], target_sec=120.0, beat_interval=0.5)
    assert all(g.play_label != "junk" for g in kept)
    assert any(g.play_label == "headshot" for g in kept)


def test_should_keep_only_multis_and_ace_clutch_singles_when_dense() -> None:
    from src.ai.engine.kill_grouping import KillGroup

    multi = KillGroup(events=(_ev(10.0), _ev(11.0), _ev(12.0)), play_label="multi")
    ace_single = KillGroup(events=(_ev(40.0, score=0.7),), play_label="ace")
    hs = KillGroup(events=(_ev(60.0, score=0.9),), play_label="headshot")
    clean = KillGroup(events=(_ev(80.0, score=0.85),), play_label="clean")
    kept = curate_plays(
        [multi, ace_single, hs, clean],
        target_sec=120.0,
        beat_interval=0.5,
        density="dense",
        clip_driven=True,
    )
    labels = {g.play_label for g in kept}
    assert "multi" in labels or any(len(g.events) >= 2 for g in kept)
    assert "ace" in labels
    assert "headshot" not in labels
    assert "clean" not in labels


def test_should_not_inflate_singles_quota_from_large_ceiling_when_clip_driven() -> None:
    from src.ai.engine.kill_grouping import KillGroup

    multi = KillGroup(events=(_ev(10.0), _ev(11.0)), play_label="multi")
    singles = [KillGroup(events=(_ev(30.0 + i * 10, score=0.8),), play_label="clean") for i in range(12)]
    kept = curate_plays(
        [multi, *singles],
        target_sec=192.0,
        beat_interval=0.5,
        density="standard",
        clip_driven=True,
    )
    n_singles = sum(1 for g in kept if len(g.events) == 1)
    assert n_singles <= 6


def test_should_order_body_by_rising_impact_into_finale() -> None:
    events = [
        _ev(10.0, score=0.9),
        _ev(11.0, score=0.9),
        _ev(12.0, score=0.9),
        _ev(50.0, score=0.65),
        _ev(80.0, score=0.85),
    ]
    ordered = with_locked_finale(build_play_flows(events))
    assert len(ordered[-1].events) == 3
    body_scores = [g.score for g in ordered[:-1]]
    assert body_scores == sorted(body_scores)
