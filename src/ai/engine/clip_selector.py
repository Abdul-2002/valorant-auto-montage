from __future__ import annotations

from dataclasses import dataclass

from src.ai.enrichment import EnrichedEvent
from src.ai.schema import CreativeBrief


@dataclass(frozen=True)
class ClipSelection:
    event_indices: list[int]


def select_event_indices(
    *,
    enriched: list[EnrichedEvent],
    brief: CreativeBrief | None,
    max_events: int,
    diversity_window_sec: float = 4.0,
    near_dup_window_sec: float = 1.2,
) -> ClipSelection:
    """
    Deterministic selection with basic diversity:
    - Start from ranked list (assumed best-first) but enforce time diversity per video
    - Apply brief curation hints if present (must_include / prefer_exclude)
    """
    n = len(enriched)
    if n == 0 or max_events <= 0:
        return ClipSelection(event_indices=[])

    # Pre-dedup: collapse near-duplicate events in the same video that happen within
    # a short window. Kept tight: multi-kill bursts a second or two apart are the
    # best montage content, and phantom killfeed duplicates are now suppressed at
    # the detector (rising-edge emission).
    # Since the incoming list is assumed ranked best-first, we keep the first occurrence.
    keep_mask = [True] * n
    kept_by_video: dict[int, list[float]] = {}
    for idx, ee in enumerate(enriched):
        v = int(ee.event.video_index)
        t = float(ee.event.timestamp_sec)
        prev_ts = kept_by_video.get(v, [])
        if any(abs(t - pt) <= near_dup_window_sec for pt in prev_ts):
            keep_mask[idx] = False
            continue
        kept_by_video.setdefault(v, []).append(t)

    # Create a stable index mapping from compacted list back to original indices.
    compact: list[tuple[int, EnrichedEvent]] = [(i, e) for i, e in enumerate(enriched) if keep_mask[i]]
    if not compact:
        return ClipSelection(event_indices=[])

    must_include: list[int] = []
    prefer_exclude: set[int] = set()
    if brief is not None:
        must_include = [i for i in brief.clip_curation.must_include if 0 <= i < n]
        prefer_exclude = {i for i in brief.clip_curation.prefer_exclude if 0 <= i < n}

    picks: list[int] = []

    def _passes_diversity(ee: EnrichedEvent) -> bool:
        for chosen_idx in picks:
            ce = enriched[chosen_idx]
            if ce.event.video_index != ee.event.video_index:
                continue
            if abs(ce.event.timestamp_sec - ee.event.timestamp_sec) < diversity_window_sec:
                return False
        return True

    # Always include must_include first (stable order).
    for idx in must_include:
        if 0 <= idx < n and keep_mask[idx] and idx not in picks:
            picks.append(idx)
        if len(picks) >= max_events:
            return ClipSelection(event_indices=picks[:max_events])

    # Then fill from remaining events in original order (ranked list), with diversity.
    for idx, ee in compact:
        if idx in prefer_exclude or idx in picks:
            continue
        if _passes_diversity(ee):
            picks.append(idx)
            if len(picks) >= max_events:
                break

    # prefer_exclude is a soft preference, NOT a ban: when the pool is short of
    # max_events (which the composer sizes from the target duration), starving
    # the timeline is worse than including a mediocre kill. Backfill from the
    # excluded set, still respecting diversity.
    if len(picks) < max_events:
        for idx, ee in compact:
            if idx not in prefer_exclude or idx in picks:
                continue
            if _passes_diversity(ee):
                picks.append(idx)
                if len(picks) >= max_events:
                    break

    return ClipSelection(event_indices=picks)
