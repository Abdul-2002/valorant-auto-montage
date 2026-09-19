#!/usr/bin/env python3
"""Measure beat-sync quality of a rendered montage.

1. Detect hard cuts in the video (frame-difference spikes).
2. Detect beats in the montage's own audio track.
3. Report distance from every cut / planned kill moment to the nearest beat.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import librosa
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.io.audio_loader import resolve_ffmpeg_exe


def detect_cuts(video: Path, *, sample_stride: int = 1) -> list[float]:
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    prev = None
    diffs: list[float] = []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % sample_stride:
            idx += 1
            continue
        small = cv2.resize(frame, (160, 90))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
        diffs.append(0.0 if prev is None else float(np.mean(np.abs(gray - prev))))
        prev = gray
        idx += 1
    cap.release()

    d = np.array(diffs)
    med = np.median(d)
    mad = np.median(np.abs(d - med)) + 1e-9
    thr = med + 10.0 * mad
    cuts: list[float] = []
    for i in range(1, len(d)):
        if d[i] > thr and d[i] > 12.0:
            t = i * sample_stride / fps
            if not cuts or t - cuts[-1] > 0.5:
                cuts.append(t)
    return cuts


def beats_of(video: Path) -> tuple[list[float], float]:
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "a.wav"
        subprocess.run(
            [resolve_ffmpeg_exe(), "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "22050", str(wav)],
            check=True, capture_output=True,
        )
        y, sr = librosa.load(str(wav), sr=22050)
    tempo, frames = librosa.beat.beat_track(y=y, sr=sr)
    return list(librosa.frames_to_time(frames, sr=sr)), float(np.atleast_1d(tempo)[0])


def nearest(t: float, grid: list[float]) -> float:
    return min(abs(t - b) for b in grid) if grid else float("nan")


def main() -> int:
    video = Path(sys.argv[1])
    script_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    beat_times, tempo = beats_of(video)
    interval = float(np.median(np.diff(beat_times))) if len(beat_times) > 1 else 0.0
    print(f"audio: tempo={tempo:.1f}bpm beats={len(beat_times)} median_interval={interval:.3f}s")

    cuts = detect_cuts(video)
    print(f"\nvideo cuts detected: {len(cuts)}")
    errs = []
    for c in cuts:
        e = nearest(c, beat_times)
        errs.append(e)
        print(f"  cut @ {c:7.3f}s -> nearest beat {e*1000:6.0f} ms away")
    if errs:
        on_beat = sum(1 for e in errs if e <= 0.10)
        print(f"cuts within 100ms of a beat: {on_beat}/{len(errs)} "
              f"(random chance ~{2*0.10/max(interval,1e-9)*100:.0f}%)")

    if script_path and script_path.exists():
        data = json.loads(script_path.read_text())
        clips = data.get("clips", [])
        offset = min(float(c["output_start_sec"]) for c in clips if c.get("output_start_sec") is not None)
        print(f"\nplanned (script) timeline, phase offset {offset:.3f}s:")
        kerrs = []
        for i, c in enumerate(clips):
            ko = c.get("kill_output_time_sec")
            os_ = c.get("output_start_sec")
            if ko is None or os_ is None:
                continue
            t = float(os_) + float(ko) - offset
            e = nearest(t, beat_times)
            kerrs.append(e)
            print(f"  clip {i}: planned kill @ {t:7.3f}s -> nearest beat {e*1000:6.0f} ms away")
        if kerrs:
            ok = sum(1 for e in kerrs if e <= 0.10)
            print(f"planned kills within 100ms of beat: {ok}/{len(kerrs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
