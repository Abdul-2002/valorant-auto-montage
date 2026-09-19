from __future__ import annotations

from dataclasses import dataclass

from src.pipeline.types import DetectedEvent


@dataclass(frozen=True)
class SelectedClip:
    video_index: int
    start_sec: float
    end_sec: float
    kill_timestamp_sec: float
    score: float


def _overlap_sec(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def select_clips(
    *,
    highlights: list[DetectedEvent],
    target_duration_sec: int,
    pre_roll_sec: float = 1.0,
    post_roll_sec: float = 1.0,
    max_clips: int = 60,
) -> list[SelectedClip]:
    """
    Convert ranked highlights into clip windows.

    This is intentionally simple for v1:
    - take top N highlights
    - make a fixed window around each highlight
    - later: map to beats and variable durations
    """
    if not highlights:
        return []

    # Conservative: average clip duration ~2s => estimate N
    est_n = max(1, min(max_clips, int(target_duration_sec / max(0.5, (pre_roll_sec + post_roll_sec)))))
    picks = highlights[:est_n]

    clips: list[SelectedClip] = []
    for h in picks:
        start = max(0.0, h.timestamp_sec - pre_roll_sec)
        end = max(start + 0.1, h.timestamp_sec + post_roll_sec)
        candidate = SelectedClip(
            video_index=h.video_index,
            start_sec=float(start),
            end_sec=float(end),
            kill_timestamp_sec=float(h.timestamp_sec),
            score=float(h.score),
        )

        # Prevent duplicate/overlapping footage from the same source video.
        # Since `highlights` is ranked best-first, we keep the first clip and drop later
        # ones that substantially overlap it.
        keep = True
        cand_dur = max(1e-9, candidate.end_sec - candidate.start_sec)
        for existing in clips:
            if existing.video_index != candidate.video_index:
                continue
            ex_dur = max(1e-9, existing.end_sec - existing.start_sec)
            ov = _overlap_sec(existing.start_sec, existing.end_sec, candidate.start_sec, candidate.end_sec)
            if ov / min(ex_dur, cand_dur) >= 0.5:
                keep = False
                break

        if keep:
            clips.append(candidate)

    return clips
