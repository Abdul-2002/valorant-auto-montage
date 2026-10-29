import numpy as np
from pydub import AudioSegment
from pydub.generators import Sine

from src.effects.audio.mixing import AudioMixingEffect, kill_gain_db
from src.effects.base import EffectContext


def _ctx(kills: tuple[float, ...]) -> EffectContext:
    return EffectContext(
        clip=None, kill_timestamp=None, beat_timestamp=None, clip_duration=0.0, fps=30,
        resolution=(1920, 1080), config={}, kill_timestamps=kills,
    )


def _tone(ms: int) -> AudioSegment:
    return Sine(440).to_audio_segment(duration=ms, volume=-20.0).set_channels(2)


def _mix(music: AudioSegment, game: AudioSegment, kills: tuple[float, ...]) -> AudioSegment:
    effect = AudioMixingEffect(music_volume_db=0.0, game_sfx_volume_db=0.0)
    return effect.apply({"music": music, "game": game}, _ctx(kills))["mixed"]


def test_should_duck_only_music_when_kill_window_is_active() -> None:
    mixed = _mix(_tone(2000), AudioSegment.silent(2000, frame_rate=44100).set_channels(2), (1.0,))
    assert abs(mixed[1050:1200].dBFS - (mixed[200:350].dBFS - 8.0)) < 0.5


def test_should_boost_game_audio_when_kill_window_is_active() -> None:
    mixed = _mix(AudioSegment.silent(2000, frame_rate=44100).set_channels(2), _tone(2000), (1.0,))
    assert abs(mixed[1050:1200].dBFS - (mixed[200:350].dBFS + 6.0)) < 0.5


def test_should_leave_audio_untouched_when_outside_kill_window() -> None:
    music = _tone(2000)
    mixed = _mix(music, AudioSegment.silent(2000, frame_rate=44100).set_channels(2), (1.0,))
    assert abs(mixed[1500:1900].dBFS - music[1500:1900].dBFS) < 0.1


def test_should_not_stack_gain_when_kill_windows_overlap() -> None:
    t = np.arange(0.0, 2000.0, 1.0)
    gain = kill_gain_db(t, (1.0, 1.1), -8.0, pre_ms=40.0, hold_ms=260.0)
    assert gain.min() == -8.0
    assert gain[0] == 0.0 and gain[-1] == 0.0
