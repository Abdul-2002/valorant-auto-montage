"""Output-time -> source-time remapping for kill-on-beat velocity edits.

A clip's retime is described by knots ``(output_sec, source_sec)`` relative to
the clip start. Kill frames are knots, so they land exactly on their beats.
A monotone cubic (PCHIP) through the knots gives smooth speed ramps without
ever running time backwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np
from scipy.interpolate import PchipInterpolator

# Output seconds between the kill frame and full slow-mo speed.
RAMP_OUT_SEC: float = 0.06
# Subdivisions of the slow segment; equal secants keep PCHIP near-linear inside it.
_SLOW_SUBDIVISIONS: int = 4
# Slowest speed tolerated anywhere (EOF clamps, short run-ups).
MIN_SEGMENT_SPEED: float = 0.25
_MIN_KNOT_GAP_SEC: float = 1e-3


@dataclass(frozen=True)
class ClipRemap:
    src_start_sec: float
    src_end_sec: float
    knots: list[tuple[float, float]]


def slowmo_factor_for_source(*, target: float, source_fps: float, min_unique_fps: float) -> float:
    """Slowest factor that still shows ``min_unique_fps`` distinct source frames per second."""
    if source_fps <= 0.0:
        return float(min(1.0, target))
    floor = float(min_unique_fps) / float(source_fps)
    return float(min(1.0, max(float(target), floor)))


def _slow_tail_knots(
    *,
    kill_out: float,
    kill_src: float,
    out_duration: float,
    src_limit: float,
    speed_in: float,
    slowmo_out: float,
    slowmo_factor: float,
    exit_speed: float,
) -> list[tuple[float, float]]:
    """Knots after the last kill: ramp down, slow segment, ramp back up to the slot end."""
    post_out = out_duration - kill_out
    slow_out = min(float(slowmo_out), max(0.0, post_out - RAMP_OUT_SEC - 0.1))
    knots: list[tuple[float, float]] = []
    t, s = kill_out, kill_src
    if slow_out > 0.05:
        ramp_speed = 0.5 * (float(speed_in) + float(slowmo_factor))
        t, s = t + RAMP_OUT_SEC, s + RAMP_OUT_SEC * ramp_speed
        knots.append((t, s))
        step = slow_out / _SLOW_SUBDIVISIONS
        for _ in range(_SLOW_SUBDIVISIONS):
            t, s = t + step, s + step * float(slowmo_factor)
            knots.append((t, s))
    tail_out = out_duration - t
    tail_src = min(tail_out * float(exit_speed), max(0.0, src_limit - s))
    tail_src = max(tail_src, tail_out * MIN_SEGMENT_SPEED)
    knots.append((out_duration, s + tail_src))
    return knots


def build_clip_remap(
    *,
    out_duration: float,
    kill_out: Sequence[float],
    kill_src: Sequence[float],
    src_bounds: tuple[float, float],
    approach_speed: float,
    slowmo_out: float,
    slowmo_factor: float,
    exit_speed: float,
) -> ClipRemap:
    """Plan the source window and retime knots for one clip.

    ``kill_out`` are kill times relative to the slot start (output domain);
    ``kill_src`` are absolute source timestamps. Both must be increasing.
    """
    if not kill_out or len(kill_out) != len(kill_src):
        raise ValueError("kill_out and kill_src must be non-empty and equal length")
    src_min, src_max = float(src_bounds[0]), float(src_bounds[1])
    pre_out = float(kill_out[0])
    src_pre = min(pre_out * float(approach_speed), float(kill_src[0]) - src_min)
    src_pre = max(src_pre, pre_out * MIN_SEGMENT_SPEED)
    src_start = max(src_min, float(kill_src[0]) - src_pre)

    abs_knots: list[tuple[float, float]] = [(0.0, src_start)]
    abs_knots += [(float(o), float(s)) for o, s in zip(kill_out, kill_src)]
    last_o, last_s = abs_knots[-1]
    prev_o, prev_s = abs_knots[-2]
    speed_in = (last_s - prev_s) / max(_MIN_KNOT_GAP_SEC, last_o - prev_o)
    abs_knots += _slow_tail_knots(
        kill_out=last_o,
        kill_src=last_s,
        out_duration=float(out_duration),
        src_limit=src_max,
        speed_in=speed_in,
        slowmo_out=slowmo_out,
        slowmo_factor=slowmo_factor,
        exit_speed=exit_speed,
    )
    rel = _strictly_increasing([(o, s - src_start) for o, s in abs_knots])
    return ClipRemap(src_start_sec=src_start, src_end_sec=src_start + rel[-1][1], knots=rel)


def _strictly_increasing(knots: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = [knots[0]]
    for o, s in knots[1:]:
        if o - out[-1][0] < _MIN_KNOT_GAP_SEC or s - out[-1][1] < _MIN_KNOT_GAP_SEC:
            continue
        out.append((float(o), float(s)))
    return out


def make_remap_fn(knots: Sequence[Sequence[float]], *, src_max: float) -> Callable[[object], object]:
    """Vectorized output->source map. Scalars in, scalars out (MoviePy video); arrays for audio."""
    pts = np.asarray(knots, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 2:
        raise ValueError("need at least two knots")
    interp = PchipInterpolator(pts[:, 0], pts[:, 1], extrapolate=True)
    hi = max(0.0, float(src_max))

    def remap(t: object) -> object:
        tt = np.atleast_1d(np.asarray(t, dtype=np.float64))
        src = np.clip(interp(tt), 0.0, hi)
        if np.ndim(t) == 0:
            return float(src[0])
        return src

    return remap
