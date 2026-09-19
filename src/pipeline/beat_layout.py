from __future__ import annotations

import logging
from dataclasses import dataclass
import numpy as np

from src.pipeline.beat_analyzer import BeatMap

logger = logging.getLogger(__name__)

# Hard minimum for any output clip slot. Below this, footage is unwatchable.
MIN_SLOT_SEC: float = 1.0

# When the beat grid would produce slots below MIN_SLOT_SEC, we treat the detected
# beats as double-time and filter them.  Any interval shorter than this is suspect.
MIN_BEAT_INTERVAL_SEC: float = 0.25


@dataclass(frozen=True)
class BeatSlot:
    clip_index: int
    output_start_sec: float
    output_end_sec: float
    beats_spanned: int
    accent_beat_sec: float = 0.0  # The beat within this slot where the kill should land

    @property
    def duration_sec(self) -> float:
        return max(0.0, float(self.output_end_sec) - float(self.output_start_sec))


@dataclass(frozen=True)
class BeatLayout:
    slots: list[BeatSlot]


def _filter_double_time(
    beats: list[float], strengths: list[float] | None = None
) -> tuple[list[float], list[float]]:
    """
    Remove beats whose interval to the previous beat is below MIN_BEAT_INTERVAL_SEC.
    Librosa frequently detects beats at double tempo (e.g. 333 BPM for a 130 BPM song).
    Strategy: compute the median inter-beat interval; keep only beats that are at least
    half the median apart from their predecessor, then de-duplicate.

    Returns (filtered_beats, filtered_strengths) kept index-aligned. Missing
    strengths default to a neutral 0.5 so accent scoring stays well-defined.
    """
    n = len(beats)
    if strengths is None or len(strengths) != n:
        strengths = [0.5] * n
    if n < 2:
        return beats, strengths

    intervals = [beats[i] - beats[i - 1] for i in range(1, n)]
    median_interval = float(np.median(intervals))

    # Threshold: anything less than half the median is likely a double-time artifact.
    # Also never allow below MIN_BEAT_INTERVAL_SEC regardless.
    thr = max(MIN_BEAT_INTERVAL_SEC, median_interval * 0.5)

    f_beats: list[float] = [beats[0]]
    f_str: list[float] = [strengths[0]]
    for b, s in zip(beats[1:], strengths[1:]):
        if b - f_beats[-1] >= thr:
            f_beats.append(b)
            f_str.append(s)

    return f_beats, f_str


def _median_interval(beats: list[float]) -> float:
    if len(beats) < 2:
        return 0.5
    intervals = [beats[i] - beats[i - 1] for i in range(1, len(beats))]
    return float(np.median(intervals))


def layout_clips_on_beats(
    *,
    beat_map: BeatMap | None,
    num_clips: int,
    pacing: float,
    target_duration_sec: int,
    start_at_beat_index: int = 0,
    max_slot_sec: float = 4.0,
) -> BeatLayout:
    """
    Create an output-timeline layout where every cut lands on a beat AND the
    total output duration fills target_duration_sec.

    Algorithm:
    1. Filter double-time beats using median interval.
    2. Compute base_k = beats that fit in target / num_clips.
    3. Each clip gets base_k beats (adjusted by arc pacing).
    4. Every slot is clamped to >= MIN_SLOT_SEC so footage is never hyperspeed.

    Falls back to uniform slots when beat_map is unavailable.
    """
    if num_clips <= 0:
        return BeatLayout(slots=[])

    target_sec = max(5, int(target_duration_sec))

    # --- Beat grid setup ---
    raw_beats = [float(x) for x in (beat_map.beat_times if beat_map is not None else [])]
    raw_strengths = [float(x) for x in (getattr(beat_map, "beat_strengths", None) or [])]
    # Sort beats and strengths together (beat_times are normally pre-sorted,
    # but strength alignment must survive any ordering).
    if raw_strengths and len(raw_strengths) == len(raw_beats):
        pairs = sorted(zip(raw_beats, raw_strengths))
        raw_beats = [p[0] for p in pairs]
        raw_strengths = [p[1] for p in pairs]
    else:
        raw_beats = sorted(raw_beats)
        raw_strengths = []
    beats, strengths = _filter_double_time(raw_beats, raw_strengths or None)

    # Fallback: no usable beat grid.
    if len(beats) < 2:
        slot_sec = max(MIN_SLOT_SEC, float(target_sec) / float(num_clips))
        logger.warning(
            "beat_layout_fallback: no_usable_beat_grid raw=%d filtered=%d — "
            "using uniform slots %.2fs each (no real beat sync).",
            len(raw_beats), len(beats), slot_sec,
        )
        return BeatLayout(slots=[
            BeatSlot(
                clip_index=i,
                output_start_sec=float(i) * slot_sec,
                output_end_sec=float(i + 1) * slot_sec,
                beats_spanned=0,
                accent_beat_sec=float(i) * slot_sec + slot_sec * 0.5,
            )
            for i in range(num_clips)
        ])

    med_interval = _median_interval(beats)
    if med_interval < MIN_BEAT_INTERVAL_SEC:
        # Pathological beat grid even after filtering — use uniform slots.
        slot_sec = max(MIN_SLOT_SEC, float(target_sec) / float(num_clips))
        logger.warning(
            "beat_layout_fallback: median_interval_too_small interval=%.3fs — "
            "using uniform slots %.2fs (no real beat sync).",
            med_interval, slot_sec,
        )
        return BeatLayout(slots=[
            BeatSlot(
                clip_index=i,
                output_start_sec=float(i) * slot_sec,
                output_end_sec=float(i + 1) * slot_sec,
                beats_spanned=0,
                accent_beat_sec=float(i) * slot_sec + slot_sec * 0.5,
            )
            for i in range(num_clips)
        ])

    # Number of filtered beats that fit within target_duration_sec.
    total_beats_available = sum(
        1 for b in beats if b <= float(target_sec)
    )
    # Fallback: use all beats if target is longer than the song.
    if total_beats_available < num_clips:
        total_beats_available = len(beats)

    # Base beats-per-clip: evenly distribute available beats across clips.
    # Clamp so the resulting slot duration is always >= MIN_SLOT_SEC and <= max_slot_sec.
    base_k = max(1, total_beats_available // num_clips)
    while base_k * med_interval < MIN_SLOT_SEC:
        base_k += 1
    while base_k * med_interval > max_slot_sec and base_k > 1:
        base_k -= 1

    logger.info(
        "beat_layout: %d clips, %d beats, median_interval=%.3fs, "
        "base_k=%d, expected_slot=%.2fs, expected_total=%.1fs (target=%ds)",
        num_clips, len(beats), med_interval,
        base_k, base_k * med_interval, num_clips * base_k * med_interval, target_sec,
    )

    slots: list[BeatSlot] = []
    bi = max(0, int(start_at_beat_index))

    for ci in range(num_clips):
        if bi >= len(beats) - 1:
            # Extend beyond last beat using the median interval.
            overshoot = bi - (len(beats) - 1)
            start = beats[-1] + overshoot * med_interval
            end = start + base_k * med_interval
        else:
            start = beats[bi]
            end_idx = min(len(beats) - 1, bi + base_k)
            end = beats[end_idx]

        # Hard floor: no slot shorter than MIN_SLOT_SEC.
        if (end - start) < MIN_SLOT_SEC:
            end = start + MIN_SLOT_SEC

        # Pick the STRONGEST beat in the slot as the accent (where the kill lands).
        # Proximity to the midpoint is only a tiebreaker: a kill on a weak
        # off-beat is technically on-grid but perceptually off — listeners feel
        # the claps/snares (high onset strength), not the metric grid.
        slot_mid = (start + end) / 2.0
        half_span = max(1e-6, (end - start) / 2.0)
        margin = 0.15 * (end - start)
        accent = start
        best_score = float("-inf")
        for b, s in zip(beats, strengths):
            if not (start <= b <= end):
                continue
            score = float(s) - 0.3 * (abs(b - slot_mid) / half_span)
            # Penalize accents at the slot edges: a kill frame on the cut itself
            # gets visually swallowed by the transition.
            if (b - start) < margin or (end - b) < margin:
                score -= 0.4
            if score > best_score:
                best_score = score
                accent = b

        slots.append(BeatSlot(
            clip_index=ci,
            output_start_sec=float(start),
            output_end_sec=float(end),
            beats_spanned=base_k,
            accent_beat_sec=float(accent),
        ))
        bi += base_k

    logger.info(
        "beat_layout: using_detected_beat_grid clips=%d filtered_beats=%d slots=%d",
        num_clips,
        len(beats),
        len(slots),
    )
    return BeatLayout(slots=slots)
