"""Pin kill stamps to the fatal gunshot instead of the kill banner.

The beat planner pins ``timestamp_sec`` to a beat. In reference montages the
banner trails the fatal shot by ~80-190 ms and the shot, not the banner, is the
one that sits on the beat (scripts/measure_kill_sync.py). Anchoring on the
shot's high-band attack makes the gunshot itself land on the beat.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import numpy as np

from src.io.audio_loader import resolve_ffmpeg_exe
from src.pipeline.types import DetectedEvent

log = logging.getLogger(__name__)

# Search window relative to the banner onset. It stops 50 ms short because the
# kill chime fires with the banner and is itself a sharp 2-8 kHz attack.
SHOT_SEARCH_SEC = (-0.30, -0.05)
# Rise over ~9 ms; window medians are useless here because sprays keep the
# level high. Utility kills and quiet windows keep the banner stamp.
MIN_ATTACK_RISE_DB = 6.0
# The attack must be one of the loudest events in the window, not a footstep.
MAX_BELOW_LOUDEST_DB = 6.0
_SR = 22050
_N_FFT = 512
_HOP = 64
_RISE_LAG = 3
_BAND_HZ = (2000.0, 8000.0)


def high_band_db(y: np.ndarray) -> np.ndarray:
    """2-8 kHz level per STFT frame (dB); gunshot cracks dominate this band."""
    if y.size < _N_FFT:
        return np.zeros(0)
    n = 1 + (y.size - _N_FFT) // _HOP
    idx = np.arange(_N_FFT)[None, :] + _HOP * np.arange(n)[:, None]
    spec = np.abs(np.fft.rfft(y[idx] * np.hanning(_N_FFT), axis=1))
    freqs = np.fft.rfftfreq(_N_FFT, 1.0 / _SR)
    band = spec[:, (freqs >= _BAND_HZ[0]) & (freqs <= _BAND_HZ[1])].sum(axis=1)
    return 20.0 * np.log10(band + 1e-6)


def shot_attack_sec(y: np.ndarray, *, window_start_sec: float, banner_sec: float) -> float | None:
    """Time of the sharpest high-band attack in the search window, or None if nothing gunshot-like."""
    db = high_band_db(y)
    if db.size <= _RISE_LAG:
        return None
    rise = db[_RISE_LAG:] - db[:-_RISE_LAG]
    times = window_start_sec + (np.arange(rise.size) * _HOP + _N_FFT / 2) / _SR
    lo, hi = banner_sec + SHOT_SEARCH_SEC[0], banner_sec + SHOT_SEARCH_SEC[1]
    in_window = (times >= lo) & (times <= hi)
    if not in_window.any():
        return None
    i = int(np.argmax(np.where(in_window, rise, -np.inf)))
    peak = float(db[i : i + 2 * _RISE_LAG + 1].max())
    loudest = float(db[: rise.size][in_window].max())
    if rise[i] < MIN_ATTACK_RISE_DB or peak < loudest - MAX_BELOW_LOUDEST_DB:
        return None
    return float(times[i])


def _read_audio_window(ffmpeg: str, video: Path, start_sec: float, dur_sec: float) -> np.ndarray:
    proc = subprocess.run(
        [
            ffmpeg, "-v", "error", "-ss", f"{start_sec:.3f}", "-t", f"{dur_sec:.3f}", "-i", str(video),
            "-vn", "-ac", "1", "-ar", str(_SR), "-f", "f32le", "-",
        ],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.float32)


def snap_kills_to_shots(highlights: list[DetectedEvent], video_paths: list[Path]) -> list[DetectedEvent]:
    """Move banner-anchored kill stamps onto the fatal shot; keep the rest."""
    ffmpeg = resolve_ffmpeg_exe()
    out = list(highlights)
    moved = total = 0
    for i, ev in enumerate(out):
        if ev.event_type != "kill" or ev.shot_anchored or not 0 <= ev.video_index < len(video_paths):
            continue
        total += 1
        start = max(0.0, ev.timestamp_sec + SHOT_SEARCH_SEC[0] - 0.1)
        dur = ev.timestamp_sec + 0.05 - start
        try:
            y = _read_audio_window(ffmpeg, video_paths[ev.video_index], start, dur)
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or b"").decode("utf-8", "replace")[-200:]
            log.warning("kill_audio_anchor: audio read failed for video %d @ %.3fs: %s", ev.video_index, ev.timestamp_sec, err)
            continue
        shot = shot_attack_sec(y, window_start_sec=start, banner_sec=ev.timestamp_sec)
        if shot is None:
            continue
        out[i] = ev.model_copy(update={"timestamp_sec": shot, "shot_anchored": True})
        moved += 1
    log.warning("kill_audio_anchor: moved %d/%d kill stamps onto the fatal shot", moved, total)
    return out
