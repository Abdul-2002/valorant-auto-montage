from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
from pydub import AudioSegment

from src.effects.base import AudioEffect, EffectContext
from src.effects.registry import register_audio_effect

_RAMP_MS = 25.0


def kill_gain_db(
    times_ms: np.ndarray, kill_times_sec: Iterable[float], gain_db: float, *, pre_ms: float, hold_ms: float
) -> np.ndarray:
    """Gain (dB) per timestamp: ``gain_db`` over [kill - pre, kill + hold], short linear ramps outside.

    Overlapping kill windows merge instead of stacking, so a double kill is not ducked twice.
    """
    weight = np.zeros(times_ms.shape, dtype=np.float64)
    for k in kill_times_sec:
        lo, hi = 1000.0 * float(k) - pre_ms, 1000.0 * float(k) + hold_ms
        edge = np.minimum(times_ms - (lo - _RAMP_MS), (hi + _RAMP_MS) - times_ms) / _RAMP_MS
        np.maximum(weight, np.clip(edge, 0.0, 1.0), out=weight)
    return weight * float(gain_db)


def _apply_kill_gain(
    seg: AudioSegment, kill_times_sec: tuple[float, ...], gain_db: float, *, pre_ms: float, hold_ms: float
) -> AudioSegment:
    if not gain_db or not kill_times_sec:
        return seg
    raw = np.array(seg.get_array_of_samples())
    samples = raw.astype(np.float64).reshape(-1, seg.channels)
    t_ms = np.arange(samples.shape[0]) * (1000.0 / seg.frame_rate)
    gain = 10.0 ** (kill_gain_db(t_ms, kill_times_sec, gain_db, pre_ms=pre_ms, hold_ms=hold_ms) / 20.0)
    peak = float(np.iinfo(raw.dtype).max)
    out = np.clip(samples * gain[:, None], -peak - 1.0, peak)
    return seg._spawn(out.astype(raw.dtype).tobytes())


@register_audio_effect("audio_mixing")
@dataclass
class AudioMixingEffect(AudioEffect):
    enabled: bool = True
    music_volume_db: float = -6.0
    game_sfx_volume_db: float = -8.0
    # Sidechain-style kill accent: the music dips and the gunshot comes forward,
    # instead of ducking the whole bus (which also buried the shot).
    kill_music_duck_db: float = -8.0
    kill_game_boost_db: float = 6.0
    kill_pre_ms: float = 40.0
    kill_hold_ms: float = 260.0

    def apply(self, audio: Any, ctx: EffectContext) -> Any:
        if not self.enabled:
            return audio
        if not isinstance(audio, dict):
            return audio

        music: AudioSegment | None = audio.get("music")
        game: AudioSegment | None = audio.get("game")
        if music is None and game is None:
            return audio

        if music is None:
            mixed = game  # type: ignore[assignment]
        elif game is None:
            mixed = music  # type: ignore[assignment]
        else:
            kills = tuple(float(k) for k in (getattr(ctx, "kill_timestamps", ()) or ()))
            window = {"pre_ms": float(self.kill_pre_ms), "hold_ms": float(self.kill_hold_ms)}
            music = _apply_kill_gain(music + float(self.music_volume_db), kills, self.kill_music_duck_db, **window)
            game = _apply_kill_gain(game + float(self.game_sfx_volume_db), kills, self.kill_game_boost_db, **window)
            mixed = music.overlay(game, gain_during_overlay=0)

        audio["mixed"] = mixed
        return audio
