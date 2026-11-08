"""Play-end boundary: hard caps, death cuts, timeline repack (no video I/O)."""

from __future__ import annotations

from src.ai.engine.play_end import (
    PlayEndConfig,
    apply_source_and_output_end,
    crosses_death_break,
    recipe_max_post_sec,
    repack_output_timeline,
    resolve_play_end_sec,
)
from src.ai.schema import ScriptClip


def _clip(
    *,
    start: float,
    end: float,
    last_kill: float,
    out_start: float,
    out_end: float,
    kill_out: float,
    recipe: str = "slow",
    video: int = 0,
) -> ScriptClip:
    return ScriptClip(
        video_index=video,
        start_sec=start,
        end_sec=end,
        kill_timestamp_sec=last_kill,
        kill_timestamps_sec=[last_kill],
        score=0.8,
        output_start_sec=out_start,
        output_end_sec=out_end,
        kill_output_times_sec=[kill_out],
        recipe=recipe,
        time_knots=[(0.0, 0.0), (kill_out, last_kill - start), (out_end - out_start, end - start)],
    )


def test_should_use_recipe_caps() -> None:
    cfg = PlayEndConfig()
    assert recipe_max_post_sec("punch", cfg) == cfg.punch_max_post_sec
    assert recipe_max_post_sec("slow", cfg) == cfg.slow_max_post_sec
    assert recipe_max_post_sec("cinematic", cfg) == cfg.cinematic_max_post_sec


def test_should_clamp_to_recipe_cap_when_no_death() -> None:
    cfg = PlayEndConfig()
    end = resolve_play_end_sec(last_kill_sec=10.0, recipe="punch", cfg=cfg)
    assert abs(end - (10.0 + cfg.punch_max_post_sec)) < 1e-6


def test_should_cut_before_death_when_earlier_than_cap() -> None:
    cfg = PlayEndConfig(slow_max_post_sec=2.0, death_pad_sec=0.15)
    end = resolve_play_end_sec(
        last_kill_sec=10.0,
        recipe="slow",
        cfg=cfg,
        death_sec=11.0,
    )
    assert abs(end - (11.0 - 0.15)) < 1e-6


def test_should_prefer_gemini_end_when_earlier() -> None:
    cfg = PlayEndConfig(slow_max_post_sec=5.0)
    end = resolve_play_end_sec(
        last_kill_sec=10.0,
        recipe="slow",
        cfg=cfg,
        gemini_end_sec=11.2,
    )
    assert abs(end - 11.2) < 1e-6


def test_should_never_end_before_last_kill() -> None:
    cfg = PlayEndConfig(death_pad_sec=0.5)
    end = resolve_play_end_sec(
        last_kill_sec=10.0,
        recipe="punch",
        cfg=cfg,
        death_sec=10.1,
    )
    assert end >= 10.0 + 0.05


def test_should_clamp_clip_source_and_output_tail() -> None:
    cfg = PlayEndConfig(slow_max_post_sec=2.0)
    clip = _clip(
        start=68.0,
        end=80.0,
        last_kill=76.0,
        out_start=15.0,
        out_end=27.0,
        kill_out=6.0,
        recipe="slow",
    )
    trimmed = apply_source_and_output_end(clip, play_end_src=77.5, cfg=cfg)
    assert trimmed.end_sec == 77.5
    assert trimmed.output_end_sec is not None
    assert trimmed.output_end_sec <= 15.0 + 6.0 + cfg.slow_max_post_sec + 1e-6
    assert trimmed.output_end_sec < 27.0


def test_should_repack_output_timeline_closing_gaps() -> None:
    a = _clip(start=0, end=10, last_kill=8, out_start=0.0, out_end=8.0, kill_out=6.0, video=0)
    b = _clip(start=20, end=30, last_kill=25, out_start=12.0, out_end=20.0, kill_out=5.0, video=1)
    # Simulate shortened first clip leaving a hole before b.
    a = a.model_copy(update={"output_end_sec": 7.0})
    packed = repack_output_timeline([a, b])
    assert packed[0].output_end_sec == 7.0
    assert packed[1].output_start_sec == 7.0
    assert abs((packed[1].output_end_sec or 0) - (packed[1].output_start_sec or 0) - 8.0) < 1e-6
    # Relative kill offset is unchanged; absolute song time slides with the pack.
    assert packed[1].kill_output_times_sec[0] == 5.0


def test_should_detect_death_break_between_kills() -> None:
    assert crosses_death_break(10.0, 16.0, [12.5]) is True
    assert crosses_death_break(10.0, 11.0, [12.5]) is False
    assert crosses_death_break(10.0, 16.0, [10.0]) is False
