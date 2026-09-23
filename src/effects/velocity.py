from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect

# Approach slower than this reads as a stuck frame for the whole pre-roll.
_MIN_APPROACH_SPEED = 0.55
# One beat of hold, not a multi-second stall. Five hits = the same picture ticks.
_DROP_HOLD_SEC = 0.42
_DROP_HOLD_HITS = 5
_NORMAL_HOLD_CAP_SEC = 0.1


def aligned_source_times(
    tt: np.ndarray,
    *,
    pre_out: float,
    slow_out: float,
    pre_src: float,
    slow_src: float,
    slowmo_fac: float,
    post_v: float,
    src_eps: float,
    drop_hold: bool,
    fps: float,
) -> np.ndarray:
    """Map output time to source time. Kill stays at the end of the slow window's first half."""
    tt = np.atleast_1d(np.asarray(tt, dtype=np.float64))
    hold = _DROP_HOLD_SEC if drop_hold else 0.0
    raw_pre_v = pre_src / pre_out if pre_out > 1e-6 else 1.0
    if raw_pre_v < _MIN_APPROACH_SPEED and pre_out > 0.08:
        slack = pre_out - (pre_src / _MIN_APPROACH_SPEED)
        cap = _DROP_HOLD_SEC if drop_hold else _NORMAL_HOLD_CAP_SEC
        hold = min(max(hold, slack), cap)
    hold = min(hold, max(0.0, pre_out - 0.05))
    approach_out = max(0.05, pre_out - hold)
    approach_v = pre_src / approach_out
    hold_start = pre_out - hold

    src = np.empty_like(tt, dtype=np.float64)
    before = tt < hold_start
    during = (tt >= hold_start) & (tt < pre_out)
    slow = (tt >= pre_out) & (tt <= pre_out + slow_out)
    after = tt > pre_out + slow_out
    src[before] = tt[before] * approach_v
    if np.any(during) and hold > 1e-4:
        u = (tt[during] - hold_start) / hold
        hit = np.minimum(_DROP_HOLD_HITS - 1, np.floor(u * _DROP_HOLD_HITS).astype(np.int32))
        # Alternate one frame back so the hold ticks instead of looking like a decode stall.
        back = np.where(hit % 2 == 1, 1.0 / max(1.0, fps), 0.0)
        src[during] = np.maximum(0.0, pre_src - back)
    elif np.any(during):
        src[during] = tt[during] * approach_v
    src[slow] = pre_src + (tt[slow] - pre_out) * float(slowmo_fac)
    src[after] = pre_src + slow_src + (tt[after] - pre_out - slow_out) * post_v
    return np.clip(src, 0.0, src_eps)


@register_clip_effect("velocity")
@dataclass
class VelocityEffect(ClipEffect):
    enabled: bool = True
    kill_slowmo_factor: float = 0.35
    kill_slowmo_duration_sec: float = 0.6
    transition_speedup_factor: float = 2.0
    easing: str = "ease_in_out_cubic"

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled or ctx.kill_timestamp is None:
            return clip

        slowmo_fac = float(ctx.config.get("_kill_slowmo_factor", self.kill_slowmo_factor))
        slowmo_dur = float(ctx.config.get("_kill_slowmo_duration_sec", self.kill_slowmo_duration_sec))

        # Kill-on-beat alignment path: the assembler provides the kill's target output
        # time (beat_timestamp = accent beat within the slot) and the source geometry.
        # We derive an exact piecewise map output-time -> source-time such that:
        #   - the kill frame appears exactly at the accent beat,
        #   - the slowmo window (output time) is centered on the accent,
        #   - the full source window maps onto the full slot (no overrun / frozen tail).
        pre_spd = ctx.config.get("_pre_kill_speed")
        post_spd = ctx.config.get("_post_kill_speed")
        src_dur = ctx.config.get("_src_duration_sec")
        anchor = ctx.beat_timestamp
        if pre_spd is not None and post_spd is not None and anchor is not None and src_dur is not None:
            out_dur = float(getattr(clip, "duration", None) or ctx.clip_duration)
            src_dur = float(src_dur)
            src_kill = float(ctx.kill_timestamp)
            anchor = float(anchor)

            slow_out = min(float(slowmo_dur), out_dur * 0.5)
            slow_src = slow_out * float(slowmo_fac)

            pre_out = anchor - slow_out / 2.0
            post_out = out_dur - anchor - slow_out / 2.0
            pre_src = src_kill - slow_src / 2.0
            post_src = (src_dur - src_kill) - slow_src / 2.0

            if pre_out > 0.05 and post_out > 0.05 and pre_src > 0.0 and post_src > 0.0:
                post_v = post_src / post_out
                src_eps = max(0.0, src_dur - 1.0 / max(1, int(ctx.fps)))
                drop_hold = bool(ctx.config.get("_beat_drop_hold"))
                fps = float(ctx.fps or 60)

                def aligned_time_map(t: Any) -> Any:
                    # MoviePy passes scalars for video frames but numpy arrays for audio.
                    tt = np.atleast_1d(np.asarray(t, dtype=np.float64))
                    src = aligned_source_times(
                        tt,
                        pre_out=pre_out,
                        slow_out=slow_out,
                        pre_src=pre_src,
                        slow_src=slow_src,
                        slowmo_fac=float(slowmo_fac),
                        post_v=post_v,
                        src_eps=src_eps,
                        drop_hold=drop_hold,
                        fps=fps,
                    )
                    if np.ndim(t) == 0:
                        return float(src[0])
                    return src

                return clip.time_transform(aligned_time_map, apply_to=["mask", "audio"])

        kill_t = float(ctx.kill_timestamp)
        half = slowmo_dur / 2.0
        slow_start = max(0.0, kill_t - half)
        slow_end = min(float(clip.duration), kill_t + half)

        # Avoid aggressive speed-up on short clips: it reads as jitter.
        trans_speed = float(self.transition_speedup_factor)
        if float(getattr(clip, "duration", 0.0) or 0.0) <= 2.0:
            trans_speed = 1.0

        def _ease_in_out_cubic(x: float) -> float:
            x = max(0.0, min(1.0, float(x)))
            return 4 * x * x * x if x < 0.5 else 1 - ((-2 * x + 2) ** 3) / 2

        # Piecewise time mapping (v1). We keep outside-window mostly identity, and
        # slow down inside the window with easing to reduce perceived discontinuities.
        def time_map(t: float) -> float:
            if t < slow_start:
                return float(t)
            if t <= slow_end:
                rel = float(t - slow_start)
                span = max(1e-9, float(slow_end - slow_start))
                u = rel / span
                eased = _ease_in_out_cubic(u)
                # eased remaps progress inside the window; apply slowmo factor to time progression.
                return float(slow_start) + float(span) * slowmo_fac * float(eased)

            # After slow window: best-effort speed-up to re-align timeline while keeping continuity.
            # This is intentionally gentle; final duration is enforced downstream.
            after = float(t - slow_end)
            return float(slow_end) + after * trans_speed

        return clip.time_transform(time_map)
