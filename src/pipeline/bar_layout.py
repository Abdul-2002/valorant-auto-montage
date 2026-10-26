"""Bar-aware kill layout: cuts on downbeats, clip length by song section.

The closing clip ends on its allocated bars. Leftover song time is not appended
to it; that tail would play out after the last kill.

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
_CHORUS_SECTIONS = frozenset({"chorus", "drop"})
BARS_BY_SECTION: dict[str, int] = {"chorus": 2, "drop": 2, "inst": 2, "solo": 2}
DEFAULT_BARS = 3
MAX_BARS_PER_CLIP = 4
FINALE_MAX_BARS = 6


def bars_needed(demand: ClipDemand, beat_interval: float) -> int:
    """Fewest whole bars that fit the run-up, every kill of the burst, and post-kill room."""
    if demand.fixed_bars is not None:
        return max(1, int(demand.fixed_bars))
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


def _grow(allocs: list[int], labels: list[str], spare: int, frozen: Sequence[bool]) -> None:
    """Give leftover bars to the finale first, then calm-section clips, then everyone.

    Frozen clips keep the length they were given (a kill-only punch, a 4–5s hold).
    """
    last = len(allocs) - 1
    while spare > 0 and not frozen[last] and allocs[last] < FINALE_MAX_BARS:
        allocs[last] += 1
        spare -= 1
    for chorus_pass in (False, True):
        grew = True
        while spare > 0 and grew:
            grew = False
            for i in range(last):
                if frozen[i]:
                    continue
                calm = labels[i] not in BARS_BY_SECTION
                if spare > 0 and allocs[i] < MAX_BARS_PER_CLIP and (calm or chorus_pass):
                    allocs[i] += 1
                    spare -= 1
                    grew = True


def _shrink(allocs: list[int], needs: list[int], excess: int) -> None:
    for i in sorted(range(len(allocs)), key=lambda i: allocs[i] - needs[i], reverse=True):
        take = min(excess, allocs[i] - needs[i])
        allocs[i] -= take
        excess -= take


def allocate_bars(
    demands: Sequence[ClipDemand], *, bar_times: Sequence[float], beat_map: BeatMap, beat_interval: float
) -> list[int]:
    """Bars per clip. Fixed-length clips are not stretched, so the sum can sit under the song."""
    total = len(bar_times) - 1
    needs = [bars_needed(d, beat_interval) for d in demands]
    allocs, labels, frozen, pos = [], [], [], 0
    for demand, need in zip(demands, needs):
        label = _label_at(beat_map, float(bar_times[min(pos, len(bar_times) - 1)]))
        if demand.fixed_bars is not None:
            allocs.append(max(1, int(demand.fixed_bars)))
            frozen.append(True)
        else:
            allocs.append(max(need, BARS_BY_SECTION.get(label, DEFAULT_BARS)))
            frozen.append(False)
        labels.append(label)
        pos += allocs[-1]
    diff = total - sum(allocs)
    if diff > 0:
        _grow(allocs, labels, diff, frozen)
    elif diff < 0:
        _shrink(allocs, needs, -diff)
    return allocs


def _first_chorus_bar(bar_times: Sequence[float], beat_map: BeatMap) -> int | None:
    for i, t in enumerate(bar_times[:-1]):
        if _label_at(beat_map, float(t)) in _CHORUS_SECTIONS:
            return i
    return None


def _anchor_index(demands: Sequence[ClipDemand]) -> int:
    """The round that should hit the chorus. The finale stays the last clip."""
    if len(demands) < 2:
        return 0
    best = max(range(len(demands) - 1), key=lambda i: (len(demands[i].src_kill_gaps), i))
    if demands[best].src_kill_gaps:
        return best
    return len(demands) - 1


def _origin_bar(
    allocs: Sequence[int], demands: Sequence[ClipDemand], bar_times: Sequence[float], beat_map: BeatMap
) -> int:
    """Bar where the montage starts so the longest run opens on the first chorus.

    Lead-in clips sit in the bars before that chorus. If the tail would run off
    the song, the whole block slides earlier and the run still overlaps the chorus.
    """
    chorus = _first_chorus_bar(bar_times, beat_map)
    if chorus is None:
        return 0
    anchor = _anchor_index(demands)
    origin = chorus - sum(allocs[:anchor])
    last = len(bar_times) - 1
    if origin + sum(allocs) > last:
        origin = last - sum(allocs)
    return max(0, origin)


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
    pos = _origin_bar(allocs, demands, bar_times, beat_map)
    for i, (demand, n_bars) in enumerate(zip(demands, allocs)):
        cut = bars[pos]
        is_last = i == len(demands) - 1
        end_pos = min(pos + n_bars, len(bars) - 1)
        if demand.pre_beats is not None:
            pre_lo = pre_hi = max(0, int(demand.pre_beats))
        else:
            pre_lo, pre_hi = pre_bounds(grid, demand)
        target = pre_lo if demand.pre_beats is not None else min(PRE_BEATS_TARGET, pre_hi)
        kills = [pick_strong(grid, cut + pre_lo, cut + pre_hi, cut + target)]
        for gap in demand.src_kill_gaps:
            kills.append(next_kill_beat(grid, kills[-1], float(gap)))
        allocated_end = float(grid.beats[bars[end_pos]])
        # Only a clip that already reaches the last bar runs out to the song end.
        end_t = float(song_end_sec) if is_last and end_pos >= len(bars) - 1 else min(float(song_end_sec), allocated_end)
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
