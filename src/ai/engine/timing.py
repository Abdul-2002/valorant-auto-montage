from __future__ import annotations

from dataclasses import dataclass

from src.ai.enrichment import EnrichedEvent
from src.pipeline.beat_analyzer import BeatMap


@dataclass(frozen=True)
class ClipTiming:
    start_sec: float
    end_sec: float
    kill_timestamp_sec: float


def compute_clip_timing(
    *,
    ev: EnrichedEvent,
    beat_map: BeatMap | None,
    pacing: float,
    beat_sync_strictness: float,
    pre_roll_bounds: tuple[float, float] = (2.0, 5.0),
    post_roll_bounds: tuple[float, float] = (1.5, 3.0),
) -> ClipTiming:
    """
    Variable clip window based on pacing:
    - higher pacing -> shorter windows
    - NOTE: beat-sync is handled in the output timeline. We must NOT snap source-video
      timestamps to music beats (they are unrelated time domains).
    """
    t = float(ev.event.timestamp_sec)
    dur = float(ev.video_duration_sec)

    pre_min, pre_max = pre_roll_bounds
    post_min, post_max = post_roll_bounds

    # pacing=0 => long clips (max roll), pacing=1 => short clips (min roll)
    pre = pre_max + (pre_min - pre_max) * float(pacing)
    post = post_max + (post_min - post_max) * float(pacing)

    start = max(0.0, t - pre)
    end = min(max(start + 0.05, t + post), dur if dur > 0 else t + post)

    return ClipTiming(start_sec=float(start), end_sec=float(end), kill_timestamp_sec=float(t))


def align_kill_to_beat(
    *,
    src_kill_offset: float,
    src_duration: float,
    slot_duration: float,
    accent_offset_in_slot: float,
    slowmo_duration: float = 0.3,
    slowmo_factor: float = 0.4,
) -> tuple[float, float, float]:
    """
    Calculate pre/post speeds so the kill frame lands on the accent beat.

    Returns (pre_kill_speed, post_kill_speed, kill_output_time_sec).

    The kill moment in source is at src_kill_offset seconds into the clip.
    We want it to appear at accent_offset_in_slot in the output timeline.

    The slowmo window (slowmo_duration of output time, centered on the accent)
    consumes slowmo_duration * slowmo_factor of source time, centered on the
    kill frame. Pre/post phases must therefore exclude that consumption,
    otherwise the kill frame arrives early and the map overruns the source.
    """
    slow_src_half = (slowmo_duration * slowmo_factor) / 2.0
    slow_out_half = slowmo_duration / 2.0

    pre_src = max(0.01, src_kill_offset - slow_src_half)
    post_src = max(0.01, (src_duration - src_kill_offset) - slow_src_half)

    pre_out = max(0.05, accent_offset_in_slot - slow_out_half)
    post_out = max(0.05, slot_duration - accent_offset_in_slot - slow_out_half)

    pre_speed = max(0.3, min(3.0, pre_src / pre_out))
    post_speed = max(0.3, min(3.0, post_src / post_out))

    return pre_speed, post_speed, accent_offset_in_slot
