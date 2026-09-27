from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from src.pipeline.beat_analyzer import BeatMap

logger = logging.getLogger(__name__)

# When the beat grid would produce slots below this, the detected beats are
# double-time; any interval shorter than this is suspect.
MIN_BEAT_INTERVAL_SEC: float = 0.25

# Absolute floor + percentile gate for "strong" accents (claps/snares).
STRONG_ACCENT_ABS: float = 0.55
STRONG_ACCENT_PERCENTILE: float = 70.0

# Output run-up before the first kill of a clip, in beats.
PRE_BEATS_MIN: int = 2
PRE_BEATS_TARGET: int = 3
PRE_BEATS_MAX: int = 4
# Beats between the last kill of one clip and the first kill of the next.
GAP_BEATS_MIN: int = 4
GAP_BEATS_MAX: int = 10
# Room after the last kill for the post-kill slow-mo + exit.
POST_BEATS_MIN: int = 2
# Playback speed assumed when converting source gaps to beat counts.
NOMINAL_SPEED: float = 1.1
MULTI_KILL_SPEED_RANGE: tuple[float, float] = (0.7, 1.9)
_FALLBACK_BPM: float = 120.0


@dataclass(frozen=True)
class ClipDemand:
    """What one montage clip needs from the beat grid."""

    src_kill_gaps: tuple[float, ...] = ()  # source seconds between consecutive kills
    src_pre_available: float = 10.0  # source seconds available before the first kill


@dataclass(frozen=True)
class ClipBeatPlan:
    output_start_sec: float
    output_end_sec: float
    kill_output_sec: tuple[float, ...]  # absolute song time of each kill
    kill_strengths: tuple[float, ...]

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.output_end_sec - self.output_start_sec)


@dataclass(frozen=True)
class _Grid:
    beats: list[float]
    strengths: list[float]
    energy: list[float]
    interval: float
    strong_thr: float


def _filter_double_time(
    beats: list[float], strengths: list[float] | None = None
) -> tuple[list[float], list[float]]:
    """Drop beats closer than half the median interval (librosa double-tempo artifacts).

    Returns (beats, strengths) index-aligned; missing strengths default to 0.5.
    """
    n = len(beats)
    if strengths is None or len(strengths) != n:
        strengths = [0.5] * n
    if n < 2:
        return beats, strengths
    median_interval = float(np.median(np.diff(beats)))
    thr = max(MIN_BEAT_INTERVAL_SEC, median_interval * 0.5)
    f_beats, f_str = [beats[0]], [strengths[0]]
    for b, s in zip(beats[1:], strengths[1:]):
        if b - f_beats[-1] >= thr:
            f_beats.append(b)
            f_str.append(s)
    return f_beats, f_str


def _strong_threshold(strengths: list[float]) -> float:
    if not strengths:
        return STRONG_ACCENT_ABS
    return max(STRONG_ACCENT_ABS, float(np.percentile(strengths, STRONG_ACCENT_PERCENTILE)))


def _energy_at_beats(beat_map: BeatMap, beats: list[float]) -> list[float]:
    """~1s-smoothed song RMS at each beat as a 0..1 percentile rank (0.5 when unavailable)."""
    rms = np.asarray(getattr(beat_map, "rms", None) or [], dtype=np.float64)
    frame_sec = float(getattr(beat_map, "rms_frame_sec", 0.0) or 0.0)
    if rms.size == 0 or not beats or frame_sec <= 0.0:
        return [0.5] * len(beats)
    win = max(1, int(round(1.0 / frame_sec)))
    smooth = np.convolve(rms, np.ones(win) / win, mode="same")
    idx = np.clip((np.asarray(beats) / frame_sec).astype(int), 0, smooth.size - 1)
    ranks = np.argsort(np.argsort(smooth[idx]))
    return [float(r) / max(1, len(ranks) - 1) for r in ranks]


def _build_grid(beat_map: BeatMap | None, target_sec: float) -> _Grid:
    raw_beats = [float(x) for x in (beat_map.beat_times if beat_map is not None else [])]
    raw_str = [float(x) for x in (getattr(beat_map, "beat_strengths", None) or [])]
    if raw_str and len(raw_str) == len(raw_beats):
        pairs = sorted(zip(raw_beats, raw_str))
        raw_beats, raw_str = [p[0] for p in pairs], [p[1] for p in pairs]
    else:
        raw_beats, raw_str = sorted(raw_beats), []
    beats, strengths = _filter_double_time(raw_beats, raw_str or None)
    interval = float(np.median(np.diff(beats))) if len(beats) >= 2 else 0.0
    if len(beats) < 2 or interval < MIN_BEAT_INTERVAL_SEC:
        logger.warning("beat_layout: no usable beat grid; using synthetic %.0f BPM grid", _FALLBACK_BPM)
        interval = 60.0 / _FALLBACK_BPM
        count = int(target_sec * 3 / interval) + 8
        beats = [i * interval for i in range(count)]
        strengths = [0.9 if i % 2 else 0.4 for i in range(count)]
        energy = [0.5] * count
    else:
        energy = _energy_at_beats(beat_map, beats) if beat_map is not None else [0.5] * len(beats)
    return _Grid(beats, strengths, energy, interval, _strong_threshold(strengths))


def beat_interval(beat_map: BeatMap | None, target_duration_sec: float = 60.0) -> float:
    """Median beat interval after double-time filtering (synthetic grid when unusable)."""
    return _build_grid(beat_map, float(target_duration_sec)).interval


def _pick_strong(grid: _Grid, lo: int, hi: int, target: int) -> int:
    """Strongest beat in [lo, hi], lightly penalized by distance from ``target``."""
    hi = min(hi, len(grid.beats) - 1)
    lo = max(0, min(lo, hi))
    best_i, best_score = lo, float("-inf")
    for j in range(lo, hi + 1):
        s = float(grid.strengths[j])
        score = 2.0 * s + (0.75 if s >= grid.strong_thr else 0.0) - 0.2 * abs(j - target)
        if score > best_score:
            best_i, best_score = j, score
    return best_i


def _next_kill_beat(grid: _Grid, prev_i: int, src_gap: float) -> int:
    """Beat for a follow-up kill in a multi-kill so playback speed stays plausible."""
    nominal = max(1, int(round(src_gap / (grid.interval * NOMINAL_SPEED))))
    lo_speed, hi_speed = MULTI_KILL_SPEED_RANGE
    candidates: list[int] = []
    for m in (nominal - 1, nominal, nominal + 1):
        j = prev_i + m
        if m < 1 or j >= len(grid.beats):
            continue
        speed = src_gap / max(1e-6, grid.beats[j] - grid.beats[prev_i])
        if lo_speed <= speed <= hi_speed:
            candidates.append(j)
    if not candidates:
        return min(len(grid.beats) - 1, prev_i + nominal)
    return max(candidates, key=lambda j: (grid.strengths[j] >= grid.strong_thr, grid.strengths[j], -abs(j - prev_i - nominal)))


def _gap_beats(grid: _Grid, beat_i: int, base_gap: int) -> int:
    """Shorter gaps in loud sections, longer in quiet ones."""
    e = grid.energy[min(beat_i, len(grid.energy) - 1)]
    adjust = -2 if e >= 0.66 else (2 if e <= 0.33 else 0)
    return int(np.clip(base_gap + adjust, GAP_BEATS_MIN, GAP_BEATS_MAX))


def _base_gap(grid: _Grid, demands: Sequence[ClipDemand], target_sec: float) -> int:
    internal = sum(
        max(1, round(g / (grid.interval * NOMINAL_SPEED))) for d in demands for g in d.src_kill_gaps
    )
    total_beats = target_sec / grid.interval
    per_clip = (total_beats - internal) / max(1, len(demands))
    return int(np.clip(round(per_clip), GAP_BEATS_MIN, GAP_BEATS_MAX))


def _pre_bounds(grid: _Grid, demand: ClipDemand) -> tuple[int, int]:
    avail_beats = int(demand.src_pre_available / (grid.interval * NOMINAL_SPEED))
    hi = max(1, min(PRE_BEATS_MAX, avail_beats))
    return min(PRE_BEATS_MIN, hi), hi


def plan_kill_accents(
    *,
    beat_map: BeatMap | None,
    demands: Sequence[ClipDemand],
    target_duration_sec: float,
    start_beat_index: int = 0,
) -> list[ClipBeatPlan]:
    """Place every kill on a (preferably strong) beat and every cut on a beat.

    Clips are contiguous on the music timeline. Returns one plan per demand that
    fits in the song; trailing demands that run past the last beat are dropped.
    """
    grid = _build_grid(beat_map, float(target_duration_sec))
    n_beats = len(grid.beats)
    base_gap = _base_gap(grid, demands, float(target_duration_sec))
    cut = max(0, min(int(start_beat_index), n_beats - 1))
    plans: list[ClipBeatPlan] = []
    for demand in demands:
        pre_lo, pre_hi = _pre_bounds(grid, demand)
        first = _pick_strong(grid, cut + pre_lo, cut + pre_hi, cut + min(PRE_BEATS_TARGET, pre_hi))
        kills = [first]
        for gap in demand.src_kill_gaps:
            kills.append(_next_kill_beat(grid, kills[-1], float(gap)))
        post = max(POST_BEATS_MIN, _gap_beats(grid, kills[-1], base_gap) - PRE_BEATS_TARGET)
        end = kills[-1] + post
        if end >= n_beats or first <= cut:
            break
        plans.append(
            ClipBeatPlan(
                output_start_sec=float(grid.beats[cut]),
                output_end_sec=float(grid.beats[end]),
                kill_output_sec=tuple(float(grid.beats[k]) for k in kills),
                kill_strengths=tuple(float(grid.strengths[k]) for k in kills),
            )
        )
        cut = end
    strong = sum(1 for p in plans for s in p.kill_strengths if s >= grid.strong_thr)
    total = sum(len(p.kill_strengths) for p in plans)
    logger.info(
        "beat_layout: %d/%d clips planned, interval=%.3fs base_gap=%d beats, strong kill accents %d/%d (thr=%.2f)",
        len(plans), len(demands), grid.interval, base_gap, strong, total, grid.strong_thr,
    )
    return plans
