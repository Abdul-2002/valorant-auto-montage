"""Bar-aware kill layout: cuts on downbeats, clip length by song section, finale runs to the song end.

Beat-only layout lands kills on beats but ignores bars and sections, so the
edit drifts against the song's phrasing. Here every cut is a bar start, busy
sections (chorus) cut faster than calm ones (intro/verse), and the last clip
absorbs the remaining bars so the montage ends with the song.
"""

from __future__ import annotations

import logging
import math
from typing import Sequence

import numpy as np

from src.pipeline.beat_analyzer import BeatMap
from src.pipeline.beat_layout import (
    NOMINAL_SPEED,
    POST_BEATS_MIN,
    PRE_BEATS_TARGET,
    BeatGrid,
    ClipBeatPlan,
    ClipDemand,
    build_grid,
    next_kill_beat,
    pick_strong,
    pre_bounds,
)

logger = logging.getLogger(__name__)

BEATS_PER_BAR = 4
BARS_BY_SECTION: dict[str, int] = {"chorus": 2, "drop": 2, "inst": 2, "solo": 2}
DEFAULT_BARS = 3
MAX_BARS_PER_CLIP = 4
FINALE_MAX_BARS = 6


def bars_needed(demand: ClipDemand, beat_interval: float) -> int:
    """Fewest whole bars that fit the run-up, every kill of the burst, and post-kill room."""
    internal = sum(max(1, round(g / (beat_interval * NOMINAL_SPEED))) + 1 for g in demand.src_kill_gaps)
    return max(2, math.ceil((PRE_BEATS_TARGET + 1 + internal + POST_BEATS_MIN) / BEATS_PER_BAR))


TARGET_AVG_BARS = 2.5


def estimate_montage_seconds(demands: Sequence[ClipDemand], *, beat_interval: float) -> float:
    """Song length the clips want: each clip at least its needed bars, ~2.5 bars on average."""
    bars = sum(max(float(bars_needed(d, beat_interval)), TARGET_AVG_BARS) for d in demands)
    return bars * BEATS_PER_BAR * beat_interval


def song_end_sec(beat_map: BeatMap) -> float:
    ends = [float(s.end_sec) for s in beat_map.sections or []]
    if ends:
        return max(ends)
    beats = beat_map.beat_times or [0.0]
    return float(beats[-1]) + (60.0 / max(1.0, float(beat_map.tempo_bpm or 120.0)))


def _bar_beat_indices(grid: BeatGrid, downbeats: Sequence[float]) -> list[int]:
    beats = np.asarray(grid.beats)
    idx = sorted({int(np.argmin(np.abs(beats - d))) for d in downbeats})
    return [i for i in idx if i < len(grid.beats)]


def _label_at(beat_map: BeatMap, t: float) -> str:
    for s in beat_map.sections or []:
        if float(s.start_sec) <= t < float(s.end_sec):
            return str(s.section_type)
    return ""


def _grow(allocs: list[int], labels: list[str], spare: int) -> None:
    """Give leftover bars to the finale first, then calm-section clips, then everyone."""
    last = len(allocs) - 1
    while spare > 0 and allocs[last] < FINALE_MAX_BARS:
        allocs[last] += 1
        spare -= 1
    for chorus_pass in (False, True):
        grew = True
        while spare > 0 and grew:
            grew = False
            for i in range(last):
                calm = labels[i] not in BARS_BY_SECTION
                if spare > 0 and allocs[i] < MAX_BARS_PER_CLIP and (calm or chorus_pass):
                    allocs[i] += 1
                    spare -= 1
                    grew = True
    allocs[last] += spare


def _shrink(allocs: list[int], needs: list[int], excess: int) -> None:
    for i in sorted(range(len(allocs)), key=lambda i: allocs[i] - needs[i], reverse=True):
        take = min(excess, allocs[i] - needs[i])
        allocs[i] -= take
        excess -= take


def allocate_bars(
    demands: Sequence[ClipDemand], *, bar_times: Sequence[float], beat_map: BeatMap, beat_interval: float
) -> list[int]:
    """Bars per clip summing exactly to the available bars (or fewer clips' worth when overfull)."""
    total = len(bar_times) - 1
    needs = [bars_needed(d, beat_interval) for d in demands]
    allocs, labels, pos = [], [], 0
    for need in needs:
        label = _label_at(beat_map, float(bar_times[min(pos, len(bar_times) - 1)]))
        allocs.append(max(need, BARS_BY_SECTION.get(label, DEFAULT_BARS)))
        labels.append(label)
        pos += allocs[-1]
    diff = total - sum(allocs)
    if diff > 0:
        _grow(allocs, labels, diff)
    elif diff < 0:
        _shrink(allocs, needs, -diff)
    return allocs


def plan_on_bars(
    *, beat_map: BeatMap, demands: Sequence[ClipDemand], song_end_sec: float
) -> list[ClipBeatPlan]:
    """One plan per demand; kills on the strongest beats inside each clip's bars."""
    grid = build_grid(beat_map, song_end_sec)
    bars = _bar_beat_indices(grid, beat_map.downbeat_times)
    if len(bars) < 3:
        raise ValueError("need at least three downbeats for bar layout")
    bar_times = [grid.beats[i] for i in bars]
    allocs = allocate_bars(demands, bar_times=bar_times, beat_map=beat_map, beat_interval=grid.interval)
    plans: list[ClipBeatPlan] = []
    pos = 0
    for i, (demand, n_bars) in enumerate(zip(demands, allocs)):
        cut = bars[pos]
        is_last = i == len(demands) - 1
        end_pos = min(pos + n_bars, len(bars) - 1)
        pre_lo, pre_hi = pre_bounds(grid, demand)
        kills = [pick_strong(grid, cut + pre_lo, cut + pre_hi, cut + min(PRE_BEATS_TARGET, pre_hi))]
        for gap in demand.src_kill_gaps:
            kills.append(next_kill_beat(grid, kills[-1], float(gap)))
        end_t = float(song_end_sec) if is_last else float(grid.beats[bars[end_pos]])
        if kills[-1] + POST_BEATS_MIN >= len(grid.beats) or grid.beats[kills[-1]] >= end_t:
            logger.warning("bar_layout: clip %d does not fit before the song end; stopping", i)
            break
        plans.append(
            ClipBeatPlan(
                output_start_sec=float(grid.beats[cut]),
                output_end_sec=end_t,
                kill_output_sec=tuple(float(grid.beats[k]) for k in kills),
                kill_strengths=tuple(float(grid.strengths[k]) for k in kills),
            )
        )
        pos = end_pos
    logger.info(
        "bar_layout: %d/%d clips on %d bars (bar=%.3fs) allocs=%s",
        len(plans), len(demands), len(bars) - 1, grid.interval * BEATS_PER_BAR, allocs,
    )
    return plans
