from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydub import AudioSegment

from src.effects.base import AudioEffect, EffectContext
from src.effects.registry import register_audio_effect


@register_audio_effect("audio_mixing")
@dataclass
class AudioMixingEffect(AudioEffect):
    enabled: bool = True
    music_volume_db: float = 0.0
    game_sfx_volume_db: float = -8.0

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
            music = music + float(self.music_volume_db)
            game = game + float(self.game_sfx_volume_db)
            mixed = music.overlay(game, gain_during_overlay=0)

        # Perceived "impact": duck the mixed bus around each kill so hits read tighter (music time).
        kill_times = getattr(ctx, "kill_timestamps", ()) or ()
        if mixed is not None and kill_times:
            duck_db = -12.0
            duck_window_ms = 300
            for k_ts in kill_times:
                k_ms = int(max(0.0, float(k_ts)) * 1000)
                start_ms = max(0, k_ms - duck_window_ms)
                end_ms = min(len(mixed), k_ms + duck_window_ms)
                if start_ms >= end_ms:
                    continue
                segment = mixed[start_ms:end_ms]
                ducked = segment + duck_db
                mixed = mixed[:start_ms] + ducked + mixed[end_ms:]

        audio["mixed"] = mixed
        return audio
