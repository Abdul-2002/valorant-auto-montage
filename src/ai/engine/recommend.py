"""Build scored recommendation payloads for the studio selector UI."""

from __future__ import annotations

from typing import Any, Sequence

from src.ai.engine.flow_scoring import pick_recommended, score_play, score_sequence
from src.ai.engine.kill_grouping import KillGroup


def play_id(group: KillGroup) -> str:
    kills = ",".join(f"{t:.2f}" for t in group.kill_secs)
    return f"{group.video_index}:{kills}"


def recommendations_payload(
    groups: Sequence[KillGroup],
    *,
    density: str = "standard",
    max_plays: int = 14,
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
    picked = pick_recommended(groups, max_plays=max_plays, density=density)
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
    }
