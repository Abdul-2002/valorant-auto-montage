"""Master-bus finishing: click-free gameplay joins, first kill above the fade-in, streaming loudness."""

from __future__ import annotations

from pydub.generators import Sine

from src.pipeline.audio_finish import (
    TARGET_LUFS,
    TARGET_TRUE_PEAK_DB,
    edge_faded,
    loudness_export_params,
    music_fade_in_ms,
)


def test_should_start_and_end_gameplay_segment_silent_when_edge_faded() -> None:
    tone = Sine(440).to_audio_segment(duration=200).apply_gain(-3)
    faded = edge_faded(tone, fade_ms=8)
    samples = faded.get_array_of_samples()
    assert abs(samples[0]) < 50
    assert abs(samples[-1]) < 600
    assert len(faded) == len(tone)


def test_should_finish_music_fade_in_before_the_first_kill() -> None:
    assert music_fade_in_ms(first_kill_sec=0.75) <= 750 - 100
    assert music_fade_in_ms(first_kill_sec=3.0) == 800
    assert music_fade_in_ms(first_kill_sec=0.05) >= 30
    assert music_fade_in_ms(first_kill_sec=None) == 800


def test_should_target_streaming_loudness_with_true_peak_ceiling() -> None:
    params = loudness_export_params()
    joined = " ".join(params)
    assert f"I={TARGET_LUFS:g}" in joined and f"TP={TARGET_TRUE_PEAK_DB:g}" in joined
    assert "-ar" in params and "44100" in params
    assert -16.0 <= TARGET_LUFS <= -13.0
