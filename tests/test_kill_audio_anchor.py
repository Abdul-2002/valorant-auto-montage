from pathlib import Path

import numpy as np

from src.detection import kill_audio_anchor as anchor
from src.pipeline.types import DetectedEvent

SR = anchor._SR


def _bed(dur_sec: float) -> np.ndarray:
    return (0.002 * np.random.default_rng(0).standard_normal(int(dur_sec * SR))).astype(np.float32)


def _with_shot(y: np.ndarray, at_sec: float) -> np.ndarray:
    out = y.copy()
    i = int(at_sec * SR)
    burst = np.random.default_rng(1).standard_normal(int(0.04 * SR)) * np.exp(-np.linspace(0, 6, int(0.04 * SR)))
    out[i : i + burst.size] += (0.5 * burst).astype(np.float32)
    return out


def test_should_find_gunshot_attack_when_shot_precedes_banner() -> None:
    y = _with_shot(_bed(0.5), 0.25)
    shot = anchor.shot_attack_sec(y, window_start_sec=10.0, banner_sec=10.4)
    assert shot is not None and abs(shot - 10.25) < 0.015


def test_should_keep_banner_when_window_has_no_gunshot() -> None:
    assert anchor.shot_attack_sec(_bed(0.5), window_start_sec=0.0, banner_sec=0.4) is None


def test_should_pick_gunshot_when_kill_chime_sits_on_banner() -> None:
    y = _with_shot(_with_shot(_bed(0.6), 0.25), 0.385)
    y[int(0.385 * SR) :] *= 3.0
    shot = anchor.shot_attack_sec(y, window_start_sec=0.0, banner_sec=0.4)
    assert shot is not None and abs(shot - 0.25) < 0.015


def test_should_ignore_shot_when_it_follows_banner() -> None:
    y = _with_shot(_bed(0.6), 0.45)
    assert anchor.shot_attack_sec(y, window_start_sec=0.0, banner_sec=0.4) is None


def test_should_move_kill_once_when_snapped_twice(monkeypatch) -> None:
    calls: list[float] = []

    def fake_read(_ffmpeg: str, _video: Path, start: float, dur: float) -> np.ndarray:
        calls.append(start)
        return _with_shot(_bed(dur), 5.25 - start)

    monkeypatch.setattr(anchor, "resolve_ffmpeg_exe", lambda: "ffmpeg")
    monkeypatch.setattr(anchor, "_read_audio_window", fake_read)
    events = [DetectedEvent(video_index=0, timestamp_sec=5.4, score=0.9, event_type="kill")]

    once = anchor.snap_kills_to_shots(events, [Path("pov.mp4")])
    twice = anchor.snap_kills_to_shots(once, [Path("pov.mp4")])

    assert once[0].shot_anchored and abs(once[0].timestamp_sec - 5.25) < 0.015
    assert twice[0] == once[0] and len(calls) == 1
