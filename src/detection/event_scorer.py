from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.pipeline.types import DetectedEvent


@dataclass(frozen=True)
class ScoringWeights:
    visual_weight: float = 0.7
    audio_weight: float = 0.3
    dedup_window_sec: float = 0.5


def _dedup(events: list[DetectedEvent], window_sec: float) -> list[DetectedEvent]:
    if not events:
        return []
    events_sorted = sorted(events, key=lambda e: e.timestamp_sec)
    out: list[DetectedEvent] = []
    cur = events_sorted[0]
    for e in events_sorted[1:]:
        if e.video_index != cur.video_index:
            out.append(cur)
            cur = e
            continue
        if abs(e.timestamp_sec - cur.timestamp_sec) <= window_sec:
            if e.score > cur.score:
                cur = e
        else:
            out.append(cur)
            cur = e
    out.append(cur)
    return out


def score_and_merge(
    *,
    visual_events: list[dict],
    audio_events: list[dict],
    weights: ScoringWeights,
) -> list[DetectedEvent]:
    """
    Merge raw visual + audio events into a unified highlight list.

    visual_events: events from template matching / YOLO detectors
    audio_events: events from audio peak detector
    """
    # Index audio peaks by (video_index, timestamp) for soft matching.
    audio_by_video: dict[int, list[dict]] = {}
    for e in audio_events:
        audio_by_video.setdefault(int(e["video_index"]), []).append(e)
    for v in audio_by_video.values():
        v.sort(key=lambda x: float(x["timestamp_sec"]))

    merged: list[DetectedEvent] = []

    # Promote visual events, attach nearest audio within dedup window.
    for ve in visual_events:
        v_idx = int(ve["video_index"])
        t = float(ve["timestamp_sec"])
        vconf = float(ve.get("score", 0.0))
        etype = str(ve.get("event_type", "kill"))

        nearest_audio = 0.0
        candidates = audio_by_video.get(v_idx, [])
        if candidates:
            # linear scan is fine for small lists; optimize later if needed
            for ae in candidates:
                dt = abs(float(ae["timestamp_sec"]) - t)
                if dt <= weights.dedup_window_sec:
                    nearest_audio = max(nearest_audio, float(ae.get("score", 0.0)))

        score = weights.visual_weight * vconf + weights.audio_weight * nearest_audio
        merged.append(
            DetectedEvent(
                video_index=v_idx,
                timestamp_sec=t,
                score=float(np.clip(score, 0.0, 1.0)),
                event_type=etype,
            )
        )

    # If we have no visual events at all, fall back to audio peaks.
    if not merged:
        for ae in audio_events:
            merged.append(
                DetectedEvent(
                    video_index=int(ae["video_index"]),
                    timestamp_sec=float(ae["timestamp_sec"]),
                    score=float(np.clip(float(ae.get("score", 0.0)), 0.0, 1.0)),
                    event_type="audio_peak",
                )
            )

    # Deduplicate in time.
    merged = _dedup(merged, weights.dedup_window_sec)

    # Sort by score desc (best highlights first).
    merged.sort(key=lambda e: e.score, reverse=True)
    return merged
