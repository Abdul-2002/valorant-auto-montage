from __future__ import annotations

import logging

from src.ai.enrichment import EnrichedEvent
from src.ai.schema import MontageScript, ScriptClip

logger = logging.getLogger(__name__)

# Hard speed caps enforced during validation.
MAX_SPEED_FACTOR: float = 2.0
MIN_SPEED_FACTOR: float = 0.1

# Minimum output slot duration for any clip.
MIN_OUTPUT_SLOT_SEC: float = 0.5


def _overlap_sec(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def validate_script(
    *,
    script: MontageScript,
    enriched_events: list[EnrichedEvent],
    video_durations_sec: list[float],
    target_duration_sec: int | None = None,
) -> MontageScript:
    """
    Best-effort semantic validation and repair:
    - clamp to video duration
    - ensure end > start
    - remove substantial overlaps within same video (keep earlier/higher-score order)
    - clamp speed_factor to [MIN_SPEED_FACTOR, MAX_SPEED_FACTOR]
    - clamp output slots to >= MIN_OUTPUT_SLOT_SEC
    - warn when total output duration is far from target
    """
    fixed: list[ScriptClip] = []

    for clip in script.clips:
        dur = video_durations_sec[clip.video_index] if 0 <= clip.video_index < len(video_durations_sec) else None
        start = max(0.0, float(clip.start_sec))
        end = float(clip.end_sec)
        if dur is not None and dur > 0:
            end = min(end, float(dur))
        end = max(start + 0.05, end)

        kill_ts = float(clip.kill_timestamp_sec)
        if dur is not None and dur > 0:
            kill_ts = min(max(0.0, kill_ts), float(dur))

        # Clamp speed_factor.
        speed = clip.speed_factor
        if speed is not None:
            clamped_speed = max(MIN_SPEED_FACTOR, min(MAX_SPEED_FACTOR, float(speed)))
            if abs(clamped_speed - float(speed)) > 0.01:
                logger.warning(
                    "validation: clamping speed_factor %.3f -> %.3f for clip at %.1fs",
                    speed, clamped_speed, float(clip.kill_timestamp_sec),
                )
                speed = clamped_speed

        # Clamp output slot to MIN_OUTPUT_SLOT_SEC.
        out_start = clip.output_start_sec
        out_end = clip.output_end_sec
        if out_start is not None and out_end is not None:
            slot_dur = float(out_end) - float(out_start)
            if slot_dur < MIN_OUTPUT_SLOT_SEC:
                logger.warning(
                    "validation: output slot %.3fs < %.3fs for clip at %.1fs; "
                    "extending to minimum.",
                    slot_dur, MIN_OUTPUT_SLOT_SEC, float(clip.kill_timestamp_sec),
                )
                out_end = float(out_start) + MIN_OUTPUT_SLOT_SEC

        candidate = clip.model_copy(update={
            "start_sec": start,
            "end_sec": end,
            "kill_timestamp_sec": kill_ts,
            "speed_factor": speed,
            "output_end_sec": out_end,
        })

        keep = True
        cand_dur = max(1e-9, candidate.end_sec - candidate.start_sec)
        for existing in fixed:
            if existing.video_index != candidate.video_index:
                continue
            ex_dur = max(1e-9, existing.end_sec - existing.start_sec)
            ov = _overlap_sec(existing.start_sec, existing.end_sec, candidate.start_sec, candidate.end_sec)
            # Single-video montages need tighter windows; 0.5 dropped too many adjacent highlights.
            if ov / min(ex_dur, cand_dur) >= 0.72:
                keep = False
                break

        if keep:
            fixed.append(candidate)

    result = script.model_copy(update={"clips": fixed})

    # Warn if total output duration is far from target.
    if target_duration_sec is not None and fixed:
        total_output = sum(
            max(0.0, float(c.output_end_sec or 0.0) - float(c.output_start_sec or 0.0))
            for c in fixed
        )
        lo = 0.5 * float(target_duration_sec)
        hi = 2.0 * float(target_duration_sec)
        if total_output < lo:
            logger.error(
                "validation: total output duration %.1fs is BELOW 50%% of target %ds (%.1fs). "
                "Montage will be too short.",
                total_output, target_duration_sec, lo,
            )
        elif total_output > hi:
            logger.error(
                "validation: total output duration %.1fs EXCEEDS 200%% of target %ds (%.1fs). "
                "Montage will be too long.",
                total_output, target_duration_sec, hi,
            )
        else:
            logger.info(
                "validation: total output duration %.1fs OK for target %ds.",
                total_output, target_duration_sec,
            )

    return result
