from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import librosa
import numpy as np


@dataclass(frozen=True)
class BeatSection:
    start_sec: float
    end_sec: float
    section_type: str  # "verse" | "chorus" | "drop" | "intro" | "outro" | "unknown"
    avg_energy: float


@dataclass(frozen=True)
class BeatMap:
    tempo_bpm: float
    beat_times: list[float]
    onset_times: list[float]
    rms: list[float]
    sections: list[BeatSection]
    # Normalized (0-1) onset strength at each beat, aligned to beat_times.
    # The perceptual accents of a song (claps, snares) are the high-strength
    # beats; kill moments must land on these, not on weak off-beats.
    beat_strengths: list[float] = field(default_factory=list)


def _rms_times(*, num_frames: int, sr: int, hop_length: int) -> list[float]:
    if num_frames <= 0:
        return []
    return [float(librosa.frames_to_time(i, sr=sr, hop_length=hop_length)) for i in range(num_frames)]


def _detect_sections(times: list[float], energy: list[float]) -> list[BeatSection]:
    """
    v1 section detector (deterministic, cheap):
    - smooth energy
    - find coarse boundaries when energy changes significantly
    - classify by average energy percentile
    """
    if len(times) < 2 or len(times) != len(energy):
        return []

    e = np.asarray(energy, dtype=np.float32)
    # Smooth with a small moving average (~1s window depending on hop length).
    win = max(3, int(round(len(e) * 0.01)))
    if win % 2 == 0:
        win += 1
    kernel = np.ones(win, dtype=np.float32) / float(win)
    es = np.convolve(e, kernel, mode="same")

    # Boundary candidates from large derivative spikes.
    d = np.abs(np.diff(es))
    if d.size == 0:
        return []
    thr = float(np.percentile(d, 92.0))
    idxs = [0]
    for i, v in enumerate(d.tolist(), start=1):
        if v >= thr:
            idxs.append(i)
    idxs.append(len(es) - 1)

    # Dedup and enforce minimum section length (~5s).
    idxs = sorted(set(int(i) for i in idxs))
    min_len_sec = 5.0
    filtered = [idxs[0]]
    for i in idxs[1:]:
        if times[i] - times[filtered[-1]] >= min_len_sec:
            filtered.append(i)
    if filtered[-1] != idxs[-1]:
        filtered.append(idxs[-1])

    # Classification by energy percentile.
    p30 = float(np.percentile(es, 30.0))
    p70 = float(np.percentile(es, 70.0))
    p90 = float(np.percentile(es, 90.0))

    sections: list[BeatSection] = []
    for a, b in zip(filtered[:-1], filtered[1:]):
        start_t = float(times[a])
        end_t = float(times[b])
        if end_t <= start_t:
            continue
        avg = float(np.mean(es[a:b])) if b > a else float(es[a])
        if avg >= p90:
            stype = "drop"
        elif avg >= p70:
            stype = "chorus"
        elif avg <= p30:
            stype = "verse"
        else:
            stype = "unknown"
        sections.append(BeatSection(start_sec=start_t, end_sec=end_t, section_type=stype, avg_energy=avg))

    # Force intro/outro if we have enough segments.
    if sections:
        sections[0] = BeatSection(
            start_sec=sections[0].start_sec,
            end_sec=sections[0].end_sec,
            section_type="intro",
            avg_energy=sections[0].avg_energy,
        )
        sections[-1] = BeatSection(
            start_sec=sections[-1].start_sec,
            end_sec=sections[-1].end_sec,
            section_type="outro",
            avg_energy=sections[-1].avg_energy,
        )
    return sections


def _beat_strengths(y: np.ndarray, sr: int, beat_times: list[float], hop_length: int = 512) -> list[float]:
    """Normalized onset-envelope strength at each beat time.

    Sampling max over a +/-1 frame window absorbs sub-frame beat placement
    error from the tracker.
    """
    if not beat_times:
        return []
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
    if env.size == 0:
        return [0.0] * len(beat_times)
    frames = np.atleast_1d(librosa.time_to_frames(np.asarray(beat_times), sr=sr, hop_length=hop_length))
    out: list[float] = []
    for f in frames.tolist():
        a = max(0, int(f) - 1)
        b = min(int(env.size), int(f) + 2)
        out.append(float(np.max(env[a:b])) if b > a else 0.0)
    peak = max(out)
    if peak <= 0.0:
        return [0.0] * len(out)
    return [v / peak for v in out]


def analyze_beats(audio_path: Path, *, start_bpm: float = 120.0, tightness: int = 100) -> BeatMap:
    y, sr = librosa.load(str(audio_path), sr=None, mono=True)
    if y.size == 0:
        return BeatMap(tempo_bpm=0.0, beat_times=[], onset_times=[], rms=[], sections=[])

    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, start_bpm=start_bpm, tightness=tightness, units="time")
    onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time", backtrack=True)
    beat_times_list = [float(x) for x in np.atleast_1d(beats).tolist()]
    strengths = _beat_strengths(y, int(sr), beat_times_list)

    hop_length = 512
    frame_length = 2048
    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
    rms = rms / (np.max(rms) + 1e-9)
    rms_times = _rms_times(num_frames=int(rms.size), sr=int(sr), hop_length=int(hop_length))
    sections = _detect_sections(rms_times, [float(x) for x in rms.tolist()])

    return BeatMap(
        tempo_bpm=float(tempo),
        beat_times=beat_times_list,
        onset_times=[float(x) for x in np.atleast_1d(onsets).tolist()],
        rms=[float(x) for x in rms.tolist()],
        sections=sections,
        beat_strengths=strengths,
    )
