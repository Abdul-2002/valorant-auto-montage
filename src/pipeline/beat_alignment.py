from __future__ import annotations

from pathlib import Path

from src.pipeline.beat_analyzer import BeatMap, analyze_beats


def detect_beats(music_path: str | Path) -> tuple[list[float], float]:
    """Detect beat timestamps. Returns (beat_times, tempo_bpm)."""
    beat_map: BeatMap = analyze_beats(Path(music_path))
    return list(beat_map.beat_times), float(beat_map.tempo_bpm)


def align_kill_to_beat(
    kill_timestamp: float,
    beat_times: list[float],
    tolerance: float = 0.2,
) -> tuple[float, bool]:
    """
    Snap a timestamp to the nearest beat if within tolerance.

    Returns: (snapped_timestamp, was_snapped)
    """
    if not beat_times:
        return float(kill_timestamp), False
    kt = float(kill_timestamp)
    nearest = min(beat_times, key=lambda b: abs(float(b) - kt))
    distance = abs(float(nearest) - kt)
    if distance <= float(tolerance):
        return float(nearest), True
    return kt, False

