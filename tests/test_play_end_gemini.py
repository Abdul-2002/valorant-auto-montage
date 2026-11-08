"""Gemini residual play-end arbiter (mocked; no network)."""

from __future__ import annotations

from pathlib import Path

from src.ai.engine.play_end_gemini import maybe_gemini_play_end, parse_play_end_response
from src.config.effect_models import PlayEndEffectConfig


def test_parse_play_end_response_clamps_to_window() -> None:
    end = parse_play_end_response(
        '{"play_end_sec": 11.1, "reason": "idle"}',
        last_kill_sec=10.0,
        until_sec=12.0,
    )
    assert end == 11.1


def test_parse_rejects_end_before_kill() -> None:
    assert (
        parse_play_end_response(
            '{"play_end_sec": 9.0, "reason": "bad"}',
            last_kill_sec=10.0,
            until_sec=12.0,
        )
        is None
    )


def test_maybe_gemini_skips_when_tail_short() -> None:
    cfg = PlayEndEffectConfig(residual_tail_sec=2.5)
    assert (
        maybe_gemini_play_end(
            video_path=Path("unused.mp4"),
            last_kill_sec=10.0,
            layer1_end_sec=11.5,
            cfg=cfg,
            api_key="fake",
            generate=lambda **_: '{"play_end_sec": 10.5}',
            sample_frames=lambda *a, **k: [b"a", b"b"],
        )
        is None
    )


def test_maybe_gemini_returns_tighter_end_on_long_tail() -> None:
    cfg = PlayEndEffectConfig(residual_tail_sec=2.5, cinematic_max_post_sec=5.0)

    def gen(**_: object) -> str:
        return '{"play_end_sec": 11.0, "reason": "death"}'

    end = maybe_gemini_play_end(
        video_path=Path("unused.mp4"),
        last_kill_sec=10.0,
        layer1_end_sec=14.0,
        cfg=cfg,
        api_key="fake",
        generate=gen,
        sample_frames=lambda *a, **k: [b"a", b"b", b"c"],
    )
    assert end == 11.0


def test_maybe_gemini_fail_open_on_generate_error() -> None:
    cfg = PlayEndEffectConfig(residual_tail_sec=2.0)

    def boom(**_: object) -> str:
        raise RuntimeError("api down")

    assert (
        maybe_gemini_play_end(
            video_path=Path("unused.mp4"),
            last_kill_sec=10.0,
            layer1_end_sec=14.0,
            cfg=cfg,
            api_key="fake",
            generate=boom,
            sample_frames=lambda *a, **k: [b"a", b"b"],
        )
        is None
    )
