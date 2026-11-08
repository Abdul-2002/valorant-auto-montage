"""Build scored recommendation payloads for the studio selector UI."""

from __future__ import annotations

from typing import Any, Sequence

from src.ai.engine.flow_scoring import pick_recommended, score_play, score_sequence
from src.ai.engine.kill_grouping import KillGroup


def play_id(group: KillGroup) -> str:
    kills = ",".join(f"{t:.2f}" for t in group.kill_secs)
    return f"{group.video_index}:{kills}"


def parse_play_id(play_id_str: str) -> tuple[int, tuple[float, ...]]:
    """Parse ``video:t1,t2,...`` studio selection ids."""
    video_s, times_s = str(play_id_str).split(":", 1)
    times = tuple(float(t) for t in times_s.split(",") if str(t).strip())
    return int(video_s), times


def resolve_locked_plays(
    groups: Sequence[KillGroup],
    selected_play_ids: Sequence[str],
) -> list[KillGroup]:
    """Keep groups that match studio selection, including death-break fragments.

    Exact ``play_id`` match still works. After Layer-2 splits a multi into singles,
    each fragment whose kills are a subset of a selected play's kill set is kept.
    """
    if not selected_play_ids:
        return []
    specs: list[tuple[int, set[float]]] = []
    for raw in selected_play_ids:
        try:
            vi, times = parse_play_id(raw)
        except (TypeError, ValueError):
            continue
        if not times:
            continue
        specs.append((vi, {round(float(t), 2) for t in times}))
    if not specs:
        return []

    exact = {str(x) for x in selected_play_ids}
    locked: list[KillGroup] = []
    seen: set[tuple[int, tuple[float, ...]]] = set()
    for group in groups:
        key = (int(group.video_index), tuple(round(float(t), 2) for t in group.kill_secs))
        if key in seen:
            continue
        if play_id(group) in exact:
            locked.append(group)
            seen.add(key)
            continue
        g_kills = set(key[1])
        for vi, sel_kills in specs:
            if int(group.video_index) != vi:
                continue
            # Fragment of a selected multi, or a selected single after rounding.
            if g_kills and g_kills <= sel_kills:
                locked.append(group)
                seen.add(key)
                break
            # Selection is a subset of a still-merged group (no split happened).
            if sel_kills and sel_kills <= g_kills:
                locked.append(group)
                seen.add(key)
                break
    locked.sort(key=lambda g: (g.kill_secs[0], g.video_index))
    return locked


def recommendations_payload(
    groups: Sequence[KillGroup],
    *,
    density: str = "standard",
    max_plays: int = 0,
    min_plays: int | None = None,
) -> dict[str, Any]:
    ranked = []
    for g in groups:
        s = score_play(g)
        ranked.append(
            {
                "id": play_id(g),
                "video_index": g.video_index,
                "kill_timestamps_sec": list(g.kill_secs),
                "kill_count": len(g.events),
                "play_label": g.play_label or "",
                "detector_score": float(g.score),
                "flow": {
                    "impact": round(s.impact, 4),
                    "watchability": round(s.watchability, 4),
                    "combined": round(s.combined, 4),
                },
                "recommended": False,
            }
        )
    picked = pick_recommended(
        groups,
        max_plays=max_plays,
        min_plays=min_plays,
        density=density,
    )
    picked_ids = {play_id(g) for g in picked}
    for row in ranked:
        row["recommended"] = row["id"] in picked_ids
    ranked.sort(key=lambda r: float(r["flow"]["combined"]), reverse=True)
    seq = score_sequence(picked)
    return {
        "plays": ranked,
        "recommended_ids": [play_id(g) for g in picked],
        "sequence_flow": {
            "pacing": round(seq.pacing, 4),
            "arc": round(seq.arc, 4),
            "variety": round(seq.variety, 4),
            "combined": round(seq.combined, 4),
        },
        "density": density,
        "recommend_max_plays": int(max_plays),
        "recommend_min_plays": None if min_plays is None else int(min_plays),
    }
