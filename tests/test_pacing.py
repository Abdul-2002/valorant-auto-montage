"""Professional montage pacing: short pre-roll, settle before fancy transitions."""

from __future__ import annotations

from src.ai.engine.pacing import (
    MAX_PRE_ROLL_SEC,
    MIN_SETTLE_BEFORE_TRANSITION_SEC,
    cap_pre_roll,
    enforce_transition_settle,
)
from src.ai.schema import ScriptClip, ScriptTransition


def test_should_cap_pre_roll_so_first_kill_lands_within_budget() -> None:
    kill_out, duration = cap_pre_roll(kill_out_rel=[2.25, 4.0], out_duration=5.0, max_pre_sec=0.75)
    assert abs(kill_out[0] - 0.75) < 1e-9
    assert abs(kill_out[1] - 2.5) < 1e-9
    # Tail must keep settle room after the last kill, not collapse onto +0.05s.
    assert duration >= kill_out[-1] + 0.75 - 1e-9
    assert kill_out[0] <= MAX_PRE_ROLL_SEC + 1e-9


def test_should_cap_pre_roll_in_whole_beats_when_beat_is_known() -> None:
    kill_out, duration = cap_pre_roll(kill_out_rel=[2.25, 4.0], out_duration=5.0, max_pre_sec=1.6, beat_sec=0.75)
    assert abs(kill_out[0] - 1.5) < 1e-9
    assert duration >= kill_out[-1] + 0.75 - 1e-9
    fast, _ = cap_pre_roll(kill_out_rel=[2.2], out_duration=4.0, max_pre_sec=1.6, beat_sec=0.44)
    assert abs(fast[0] - 3 * 0.44) < 1e-9


def test_should_allow_one_full_beat_of_pre_roll_when_beat_exceeds_budget() -> None:
    kill_out, _ = cap_pre_roll(kill_out_rel=[2.0], out_duration=3.0, max_pre_sec=0.6, beat_sec=1.0)
    assert abs(kill_out[0] - 1.0) < 1e-9


def test_should_give_setups_about_two_beats_at_montage_tempos() -> None:
    assert 1.2 <= MAX_PRE_ROLL_SEC <= 1.8


def test_should_leave_short_pre_roll_unchanged() -> None:
    kill_out, duration = cap_pre_roll(kill_out_rel=[0.5], out_duration=2.0, max_pre_sec=0.75)
    assert kill_out == [0.5]
    assert duration == 2.0


def test_should_downgrade_jigsaw_when_settle_after_kill_is_too_short() -> None:
    clips = [
        ScriptClip(
            video_index=0,
            start_sec=0.0,
            end_sec=2.0,
            kill_timestamp_sec=1.0,
            score=0.9,
            output_start_sec=0.0,
            output_end_sec=2.0,
            kill_output_times_sec=[1.5],
            transition_to_next=ScriptTransition(type="jigsaw", duration_sec=0.75),
        ),
        ScriptClip(
            video_index=1,
            start_sec=0.0,
            end_sec=2.0,
            kill_timestamp_sec=1.0,
            score=0.9,
            output_start_sec=2.0,
            output_end_sec=4.0,
            kill_output_times_sec=[1.0],
            transition_to_next=None,
        ),
    ]
    out = enforce_transition_settle(clips, min_settle_sec=MIN_SETTLE_BEFORE_TRANSITION_SEC)
    assert out[0].transition_to_next is not None
    assert out[0].transition_to_next.type == "hard_cut"
    assert out[0].transition_to_next.duration_sec <= 0.12


def test_should_keep_jigsaw_when_settle_is_enough() -> None:
    clips = [
        ScriptClip(
            video_index=0,
            start_sec=0.0,
            end_sec=4.0,
            kill_timestamp_sec=1.0,
            score=0.9,
            output_start_sec=0.0,
            output_end_sec=4.0,
            kill_output_times_sec=[1.5],
            transition_to_next=ScriptTransition(type="jigsaw", duration_sec=0.5),
        ),
        ScriptClip(
            video_index=1,
            start_sec=0.0,
            end_sec=2.0,
            kill_timestamp_sec=1.0,
            score=0.9,
            output_start_sec=4.0,
            output_end_sec=6.0,
            kill_output_times_sec=[1.0],
        ),
    ]
    out = enforce_transition_settle(clips, min_settle_sec=1.2)
    assert out[0].transition_to_next is not None
    assert out[0].transition_to_next.type == "jigsaw"
