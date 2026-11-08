"""Studio selection must survive death-break play_id splits."""

from __future__ import annotations

from src.ai.engine.kill_grouping import KillGroup
from src.ai.engine.recommend import parse_play_id, play_id, resolve_locked_plays
from src.ai.enrichment import EnrichedEvent
from src.pipeline.types import DetectedEvent


def _group(*times: float, video: int = 0, score: float = 0.8) -> KillGroup:
    events = tuple(
        EnrichedEvent(
            event=DetectedEvent(video_index=video, timestamp_sec=t, score=score, event_type="kill"),
            video_duration_sec=300.0,
            gap_prev_sec=None,
            gap_next_sec=None,
            multi_kill_group_id=None,
        )
        for t in times
    )
    return KillGroup(events)


def test_parse_play_id() -> None:
    assert parse_play_id("13:77.73,88.58,90.58") == (13, (77.73, 88.58, 90.58))


def test_exact_selection_ids_still_lock() -> None:
    g = _group(10.0, 12.0, video=1)
    locked = resolve_locked_plays([g, _group(50.0, video=2)], [play_id(g)])
    assert len(locked) == 1
    assert locked[0].kill_secs == (10.0, 12.0)


def test_death_break_fragments_still_match_original_selection() -> None:
    # Studio selected a triple; Layer 2 split it into three singles.
    fragments = [_group(77.73, video=13), _group(88.58, video=13), _group(90.58, video=13)]
    other = _group(1.0, video=0)
    locked = resolve_locked_plays(
        fragments + [other],
        ["13:77.73,88.58,90.58"],
    )
    assert sorted(t for g in locked for t in g.kill_secs) == [77.73, 88.58, 90.58]
    assert all(g.video_index == 13 for g in locked)


def test_unrelated_kills_on_same_video_are_not_locked() -> None:
    locked = resolve_locked_plays(
        [_group(10.0, video=1), _group(40.0, video=1)],
        ["1:10.00,12.00"],
    )
    assert [list(g.kill_secs) for g in locked] == [[10.0]]
