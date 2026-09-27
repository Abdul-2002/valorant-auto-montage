from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.detection.scope_state import detect_scoped_before_kills
from src.io.video_reader import get_video_info
from src.pipeline.types import DetectedEvent


@dataclass(frozen=True)
class EnrichedEvent:
    event: DetectedEvent
    video_duration_sec: float
    gap_prev_sec: float | None
    gap_next_sec: float | None
    multi_kill_group_id: int | None
    source_fps: float = 60.0
    scoped: bool = False


def _group_multi_kills(events: list[DetectedEvent], *, window_sec: float = 5.0) -> dict[int, int]:
    """
    Assign a group id to events that happen close together within the same video.
    Returns a mapping of index -> group_id.
    """
    idx_to_group: dict[int, int] = {}
    next_gid = 0

    by_video: dict[int, list[tuple[int, DetectedEvent]]] = {}
    for idx, ev in enumerate(events):
        by_video.setdefault(ev.video_index, []).append((idx, ev))

    for _, items in by_video.items():
        items.sort(key=lambda x: x[1].timestamp_sec)
        current: list[tuple[int, DetectedEvent]] = []

        def flush() -> None:
            nonlocal next_gid
            if len(current) >= 2:
                for i, _ev in current:
                    idx_to_group[i] = next_gid
                next_gid += 1
            current.clear()

        for idx, ev in items:
            if not current:
                current.append((idx, ev))
                continue
            if (ev.timestamp_sec - current[-1][1].timestamp_sec) <= window_sec:
                current.append((idx, ev))
            else:
                flush()
                current.append((idx, ev))
        flush()

    return idx_to_group


def _scoped_flags(highlights: list[DetectedEvent], video_paths: list[Path]) -> dict[int, bool]:
    by_video: dict[int, list[int]] = {}
    for idx, ev in enumerate(highlights):
        by_video.setdefault(int(ev.video_index), []).append(idx)
    flags: dict[int, bool] = {}
    for vi, idxs in by_video.items():
        if not 0 <= vi < len(video_paths):
            continue
        hits = detect_scoped_before_kills(video_paths[vi], [float(highlights[i].timestamp_sec) for i in idxs])
        flags.update(zip(idxs, hits))
    return flags


def enrich_events(
    *, highlights: list[DetectedEvent], video_paths: list[Path], detect_scope: bool = True
) -> tuple[list[EnrichedEvent], list[float]]:
    """
    Enrich events with per-video duration/fps, neighbor gaps and local CV features.
    Returns (enriched_events, video_durations_sec).
    """
    durations: list[float] = []
    fps_by_video: list[float] = []
    for p in video_paths:
        info = get_video_info(p)
        durations.append(float(info.duration_sec))
        fps_by_video.append(float(info.fps or 60.0))

    # gaps based on time-order within each video
    by_video: dict[int, list[tuple[int, DetectedEvent]]] = {}
    for idx, ev in enumerate(highlights):
        by_video.setdefault(ev.video_index, []).append((idx, ev))
    for _, items in by_video.items():
        items.sort(key=lambda x: x[1].timestamp_sec)

    gap_prev: dict[int, float | None] = {i: None for i in range(len(highlights))}
    gap_next: dict[int, float | None] = {i: None for i in range(len(highlights))}
    for _, items in by_video.items():
        for j, (idx, ev) in enumerate(items):
            if j > 0:
                gap_prev[idx] = float(ev.timestamp_sec - items[j - 1][1].timestamp_sec)
            if j + 1 < len(items):
                gap_next[idx] = float(items[j + 1][1].timestamp_sec - ev.timestamp_sec)

    groups = _group_multi_kills(highlights)
    scoped = _scoped_flags(highlights, video_paths) if detect_scope else {}

    enriched: list[EnrichedEvent] = []
    for idx, ev in enumerate(highlights):
        in_range = 0 <= ev.video_index < len(durations)
        enriched.append(
            EnrichedEvent(
                event=ev,
                video_duration_sec=float(durations[ev.video_index]) if in_range else 0.0,
                gap_prev_sec=gap_prev.get(idx),
                gap_next_sec=gap_next.get(idx),
                multi_kill_group_id=groups.get(idx),
                source_fps=float(fps_by_video[ev.video_index]) if in_range else 60.0,
                scoped=bool(scoped.get(idx, False)),
            )
        )
    return enriched, durations
