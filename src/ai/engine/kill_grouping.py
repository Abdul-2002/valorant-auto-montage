"""Group close kills into one continuous montage clip (multi-kill sequences).

Separate fixed windows for kills 1-2s apart overlap in source time, so the
viewer sees the same footage twice. One clip per burst, with every kill on
its own beat, is how editors cut multi-kills.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from src.ai.enrichment import EnrichedEvent
from src.pipeline.beat_layout import GAP_BEATS_MIN, NOMINAL_SPEED, ClipDemand

MAX_KILL_GAP_SEC: float = 2.2
MAX_KILLS_PER_CLIP: int = 5


@dataclass(frozen=True)
class KillGroup:
    events: tuple[EnrichedEvent, ...]

    @property
    def video_index(self) -> int:
        return int(self.events[0].event.video_index)

    @property
    def kill_secs(self) -> tuple[float, ...]:
        return tuple(float(e.event.timestamp_sec) for e in self.events)

    @property
    def score(self) -> float:
        return max(float(e.event.score) for e in self.events)

    @property
    def scoped(self) -> bool:
        return bool(self.events[-1].scoped)

    @property
    def source_fps(self) -> float:
        return float(self.events[0].source_fps)

    @property
    def video_duration_sec(self) -> float:
        return float(self.events[0].video_duration_sec)

    def demand(self) -> ClipDemand:
        secs = self.kill_secs
        return ClipDemand(
            src_kill_gaps=tuple(b - a for a, b in zip(secs, secs[1:])),
            src_pre_available=secs[0],
        )


def group_kills(
    events: Sequence[EnrichedEvent],
    *,
    max_gap_sec: float = MAX_KILL_GAP_SEC,
    max_kills: int = MAX_KILLS_PER_CLIP,
) -> list[KillGroup]:
    """Split each video's kills into bursts; montage order follows source time."""
    by_video: dict[int, list[EnrichedEvent]] = {}
    for ev in events:
        by_video.setdefault(int(ev.event.video_index), []).append(ev)
    groups: list[KillGroup] = []
    for items in by_video.values():
        items.sort(key=lambda e: float(e.event.timestamp_sec))
        current: list[EnrichedEvent] = []
        for ev in items:
            gap = float(ev.event.timestamp_sec) - float(current[-1].event.timestamp_sec) if current else 0.0
            if current and (gap > max_gap_sec or len(current) >= max_kills):
                groups.append(KillGroup(tuple(current)))
                current = []
            current.append(ev)
        if current:
            groups.append(KillGroup(tuple(current)))
    groups.sort(key=lambda g: (g.kill_secs[0], g.video_index))
    return groups


def _group_value(group: KillGroup) -> tuple[int, float]:
    return len(group.events), group.score


def _min_output_sec(group: KillGroup, beat_interval: float) -> float:
    internal = sum(group.demand().src_kill_gaps) / NOMINAL_SPEED
    return GAP_BEATS_MIN * beat_interval + internal


def fit_groups_to_duration(
    groups: Sequence[KillGroup],
    *,
    target_sec: float,
    beat_interval: float,
    min_clip_sec: Callable[[KillGroup], float] | None = None,
) -> list[KillGroup]:
    """Drop the weakest bursts until the tightest possible layout fits ``target_sec``."""
    cost = min_clip_sec or (lambda g: _min_output_sec(g, beat_interval))
    kept = list(groups)
    while len(kept) > 1 and sum(cost(g) for g in kept) > target_sec:
        kept.remove(min(kept, key=_group_value))
    return kept


def move_finale_last(groups: Sequence[KillGroup]) -> list[KillGroup]:
    """The biggest burst closes the montage (editors save the best play for the end)."""
    if len(groups) < 2:
        return list(groups)
    finale = max(groups, key=_group_value)
    return [g for g in groups if g is not finale] + [finale]
