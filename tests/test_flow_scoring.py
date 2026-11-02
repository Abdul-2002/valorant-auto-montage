"""Flow scoring prefers impactful sequences over junk / punch spam."""

from __future__ import annotations

from src.ai.engine.flow_scoring import pick_recommended, score_play, score_sequence
from src.ai.engine.kill_grouping import KillGroup
from src.ai.enrichment import EnrichedEvent
from src.pipeline.types import DetectedEvent


def _ev(t: float, video: int = 0, score: float = 0.8, *, event_type: str = "kill") -> EnrichedEvent:
    return EnrichedEvent(
        event=DetectedEvent(video_index=video, timestamp_sec=t, score=score, event_type=event_type),
        video_duration_sec=300.0,
        gap_prev_sec=None,
        gap_next_sec=None,
        multi_kill_group_id=None,
        scoped=False,
    )


def test_should_rank_junk_below_multi() -> None:
    multi = KillGroup(events=(_ev(10), _ev(11), _ev(12)), play_label="multi")
    junk = KillGroup(events=(_ev(40, score=0.95),), play_label="junk")
    assert score_play(multi).combined > score_play(junk).combined


def test_should_score_mixed_sequence_higher_than_single_spam() -> None:
    mixed = [
        KillGroup(events=(_ev(10, score=0.7),), play_label="headshot"),
        KillGroup(events=(_ev(20), _ev(21)), play_label="multi"),
        KillGroup(events=(_ev(40), _ev(41), _ev(42), _ev(43)), play_label="ace"),
    ]
    spam = [KillGroup(events=(_ev(10.0 + i * 5, score=0.55),), play_label="clean") for i in range(6)]
    assert score_sequence(mixed).combined > score_sequence(spam).combined


def test_should_pick_recommended_keeping_multi_finale() -> None:
    plays = [
        KillGroup(events=(_ev(10, score=0.6),), play_label="clean"),
        KillGroup(events=(_ev(20, score=0.7),), play_label="headshot"),
        KillGroup(events=(_ev(40), _ev(41), _ev(42)), play_label="multi"),
        KillGroup(events=(_ev(60, score=0.9),), play_label="junk"),
    ]
    picked = pick_recommended(plays, max_plays=4, density="standard")
    assert picked
    assert picked[-1].play_label == "multi"
    assert all(g.play_label != "junk" for g in picked)
