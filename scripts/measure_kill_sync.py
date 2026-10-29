#!/usr/bin/env python3
"""Measure kill / gunshot / cut sync against the music, plus sparkle density at kills.

Same numbers for reference montages and our renders, so "same flow" is measurable:

- kill_beat     kill-banner onset -> nearest beat (signed ms, + = late)
- shot_beat     sharpest 2-8 kHz rise in the 350 ms before the banner (the fatal
                shot) -> nearest beat
- shot_punch_db that transient's 2-8 kHz level above the track's median 2-8 kHz level
- cut_beat      hard cuts -> nearest beat; cuts_per_min
- sparkle       small bright blobs per frame in [kill, kill + 0.5 s] vs the whole video

Kills come from ``<run>/montage_script.json`` for our renders (exact), else from
the HUD banner-pop detector. The detector is noisy on edited footage (flashes and
zooms), so the per-file kill count and ``kill_source`` are reported.
``chance_within_50ms_pct`` is what uniformly random timing would score.

Usage (inside the render image):
    python scripts/measure_kill_sync.py artifacts/ref_yt/*.video.mp4 artifacts/run31/outputs/montage_16x9.mp4
"""
from __future__ import annotations

import argparse
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

from src.detection.kill_frame_refine import is_banner_pop, kill_skull_score
from src.io.audio_loader import resolve_ffmpeg_exe
from src.pipeline.beat_analyzer import analyze_beats
from src.youtube.listing import load_shot_times

_SR = 22050
_HOP = 128
_HOP_SEC = _HOP / _SR
_SHOT_LOOKBACK_SEC = 0.35
_SHOT_LOOKAHEAD_SEC = 0.03
_PUNCH_WINDOW_SEC = 0.06
_KILL_DEBOUNCE_SEC = 0.5
_CUT_DEBOUNCE_SEC = 0.1
_SKULL_MIN = 0.35
_SAMPLE_HZ = 30.0
_ANALYSIS_SIZE = (960, 540)
_CUT_CORR = 0.55
_SPARKLE_V = 240
_SPARKLE_AREA = (2, 40)
_SPARKLE_WINDOW_SEC = 0.5
_SYNC_TOL_MS = 50.0
_SHEET_OFFSETS = (0.0, 0.1, 0.2, 0.35)
_SHEET_ROWS = 6


def _audio_for(video: Path) -> Path:
    """Sibling ``<id>.audio.*`` for split yt-dlp downloads, else the video's own track."""
    if video.name.endswith(".video.mp4"):
        base = video.name[: -len(".video.mp4")]
        for cand in sorted(video.parent.glob(f"{base}.audio.*")):
            return cand
    return video


def _load_audio(src: Path) -> tuple[np.ndarray, np.ndarray]:
    """(mono samples at _SR, beat times) for any container ffmpeg can read."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "track.wav"
        subprocess.run(
            [resolve_ffmpeg_exe(), "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", str(_SR), str(wav)],
            check=True,
        )
        y, _ = librosa.load(str(wav), sr=_SR, mono=True)
        beats = np.asarray(analyze_beats(wav).beat_times, dtype=np.float64)
    return y, beats


def _high_band_db(y: np.ndarray) -> np.ndarray:
    spec = np.abs(librosa.stft(y, n_fft=1024, hop_length=_HOP))
    freqs = librosa.fft_frequencies(sr=_SR, n_fft=1024)
    band = spec[(freqs >= 2000.0) & (freqs <= 8000.0)].sum(axis=0)
    return 20.0 * np.log10(band + 1e-6)


def _fatal_shot(hf_db: np.ndarray, kill_sec: float) -> tuple[float, float]:
    """(time, peak dB) of the sharpest high-band rise just before the banner."""
    a = max(1, int((kill_sec - _SHOT_LOOKBACK_SEC) / _HOP_SEC))
    b = min(hf_db.size, int((kill_sec + _SHOT_LOOKAHEAD_SEC) / _HOP_SEC) + 1)
    if b - a < 2:
        return kill_sec, float("nan")
    i = a + int(np.argmax(hf_db[a:b] - hf_db[a - 1 : b - 1]))
    peak = float(np.max(hf_db[i : min(hf_db.size, i + int(_PUNCH_WINDOW_SEC / _HOP_SEC) + 1)]))
    return i * _HOP_SEC, peak


def _offset_ms(t: float, beats: np.ndarray) -> float:
    return 1000.0 * (t - float(beats[int(np.argmin(np.abs(beats - t)))]))


def _hsv_hist(small: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
    return cv2.normalize(hist, hist).flatten()


def _sparkle_count(small: np.ndarray) -> int:
    v = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)[:, :, 2]
    mask = (v >= _SPARKLE_V).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    areas = stats[1:, cv2.CC_STAT_AREA]
    return int(np.count_nonzero((areas >= _SPARKLE_AREA[0]) & (areas <= _SPARKLE_AREA[1])))


def _append_debounced(times: list[float], t: float, gap: float) -> None:
    if not times or t - times[-1] > gap:
        times.append(t)


def _scan_video(path: Path) -> tuple[list[float], list[float], list[tuple[float, int]], float]:
    """(kill times, cut times, (t, sparkle count) samples, duration) in one decode pass."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    step = max(1, int(round(fps / _SAMPLE_HZ)))
    kills: list[float] = []
    cuts: list[float] = []
    sparkles: list[tuple[float, int]] = []
    prev_gray = prev_hist = None
    pending: float | None = None
    i = 0
    try:
        while True:
            if i % step:
                if not cap.grab():
                    break
                i += 1
                continue
            ok, frame = cap.read()
            if not ok:
                break
            t = i / fps
            small = cv2.resize(frame, _ANALYSIS_SIZE, interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            hist = _hsv_hist(small)
            pop = prev_gray is not None and is_banner_pop(prev_gray, gray)
            if pop or pending is not None:
                # The skull can trail the banner pop by a frame; give it one more sample.
                if kill_skull_score(frame) >= _SKULL_MIN:
                    _append_debounced(kills, pending if pending is not None else t, _KILL_DEBOUNCE_SEC)
                    pending = None
                else:
                    pending = t if pending is None and pop else None
            if prev_hist is not None and cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL) < _CUT_CORR:
                _append_debounced(cuts, t, _CUT_DEBOUNCE_SEC)
            sparkles.append((t, _sparkle_count(small)))
            prev_gray, prev_hist = gray, hist
            i += 1
    finally:
        cap.release()
    return kills, cuts, sparkles, i / fps


def _offset_stats(offsets: list[float]) -> dict[str, float]:
    if not offsets:
        return {"n": 0}
    a = np.abs(np.asarray(offsets))
    return {
        "n": len(offsets),
        "median_abs_ms": round(float(np.median(a)), 1),
        "within_50ms_pct": round(100.0 * float(np.mean(a <= _SYNC_TOL_MS)), 1),
        "median_signed_ms": round(float(np.median(offsets)), 1),
    }


def _sparkle_stats(sparkles: list[tuple[float, int]], kills: list[float]) -> dict[str, float]:
    if not sparkles:
        return {"kill": 0.0, "base": 0.0}
    times = np.asarray([t for t, _ in sparkles])
    counts = np.asarray([c for _, c in sparkles], dtype=np.float64)
    in_kill = np.zeros(times.size, dtype=bool)
    for k in kills:
        in_kill |= (times >= k) & (times <= k + _SPARKLE_WINDOW_SEC)
    kill_mean = float(counts[in_kill].mean()) if in_kill.any() else 0.0
    return {"kill": round(kill_mean, 1), "base": round(float(counts.mean()), 1)}


def _kill_sheet(video: Path, kills: list[float], out_path: Path) -> None:
    """Contact sheet: rows = kills, columns = kill + offsets, for eyeballing glitter."""
    if not kills:
        return
    picks = kills[:: max(1, len(kills) // _SHEET_ROWS)][:_SHEET_ROWS]
    cap = cv2.VideoCapture(str(video))
    rows = []
    try:
        for k in picks:
            tiles = []
            for o in _SHEET_OFFSETS:
                cap.set(cv2.CAP_PROP_POS_MSEC, (k + o) * 1000.0)
                ok, f = cap.read()
                tiles.append(cv2.resize(f, (480, 270)) if ok else np.zeros((270, 480, 3), np.uint8))
            rows.append(np.hstack(tiles))
    finally:
        cap.release()
    cv2.imwrite(str(out_path), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])


def _script_timeline(video: Path) -> tuple[list[float], np.ndarray] | None:
    """(kill times, song beat grid) on the montage timeline for our own renders.

    Beat tracking on the final mix can lock to a different tempo than the song
    (game audio adds onsets), so our renders are scored against the song's grid.
    """
    run = video.parent.parent
    script = run / "montage_script.json"
    songs = sorted((run / "song").glob("*.wav"))
    if video.parent.name != "outputs" or not script.is_file() or not songs:
        return None
    clips = json.loads(script.read_text(encoding="utf-8")).get("clips") or []
    if not clips:
        return None
    phase = min(float(c["output_start_sec"]) for c in clips)
    beats = np.asarray(analyze_beats(songs[0]).beat_times, dtype=np.float64) - phase
    return load_shot_times(script), beats


def measure(video: Path, sheet_dir: Path) -> dict[str, object]:
    y, beats = _load_audio(_audio_for(video))
    timeline = _script_timeline(video)
    if timeline is not None:
        beats = timeline[1]
    if beats.size < 2:
        raise RuntimeError(f"no beat grid for {video}")
    hf = _high_band_db(y)
    hud_kills, cuts, sparkles, dur = _scan_video(video)
    script_kills = timeline[0] if timeline is not None else None
    kills = script_kills if script_kills is not None else hud_kills
    shots = [_fatal_shot(hf, k) for k in kills]
    median_hf = float(np.median(hf))
    punches = [p - median_hf for _, p in shots if np.isfinite(p)]
    interval_ms = 1000.0 * float(np.median(np.diff(beats)))
    _kill_sheet(video, kills, sheet_dir / f"{video.stem}_kills.jpg")
    return {
        "file": video.name,
        "duration_sec": round(dur, 1),
        "tempo_bpm": round(60000.0 / interval_ms, 1),
        "chance_within_50ms_pct": round(100.0 * 2.0 * _SYNC_TOL_MS / interval_ms, 1),
        "kill_source": "script" if script_kills is not None else "hud",
        "kills": len(kills),
        "hud_kills": len(hud_kills),
        "kill_beat": _offset_stats([_offset_ms(k, beats) for k in kills]),
        "shot_beat": _offset_stats([_offset_ms(t, beats) for t, _ in shots]),
        "shot_lead_ms": round(float(np.median([1000.0 * (k - t) for k, (t, _) in zip(kills, shots)])), 1) if kills else None,
        "shot_punch_db": round(float(np.median(punches)), 1) if punches else None,
        "cuts_per_min": round(60.0 * len(cuts) / max(dur, 1e-6), 1),
        "cut_beat": _offset_stats([_offset_ms(c, beats) for c in cuts]),
        "sparkle": _sparkle_stats(sparkles, kills),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Kill/gunshot/cut-to-beat sync and sparkle metrics")
    p.add_argument("videos", type=Path, nargs="+")
    p.add_argument("--report", type=Path, default=ROOT / "artifacts/ref_yt/kill_sync_report.json")
    args = p.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for video in args.videos:
        if not video.is_file():
            print(f"missing: {video}", file=sys.stderr)
            return 1
        print(f"measuring {video.name} ...", flush=True)
        row = measure(video, args.report.parent)
        rows.append(row)
        print(json.dumps(row), flush=True)
    args.report.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
