from __future__ import annotations

import json
from typing import Any

from src.ai.enrichment import EnrichedEvent


SYSTEM_PROMPT = """You are a professional Valorant montage editor directing an editing engine.

You will be given:
- A ranked list of detected kills with timestamps, scores and multi-kill grouping
- A music summary: tempo, song sections with energy levels, and beat-accent statistics
- A style configuration (creative_config)

You do NOT generate clip timestamps. You output a creative brief the engine executes.
The engine always lands every kill exactly on a beat; you decide how each kill feels.

DIRECTING PRINCIPLES (Zishu-style Valorant edits):
1. Every kill gets a hit on the beat. Pick a "hit_style" per kill and VARY them;
   the same hit on every kill looks templated:
   - "flash_blur": brightness flash + lens blur that decays (the Zishu default).
   - "glow": bloom on bright pixels (skins, muzzle flash, abilities).
   - "flash_shake": flash + short camera shake (heavy hits, shotguns, Operator).
2. Per-kill "recipe" controls what happens after the hit:
   - "slow": post-kill slow motion (knife pull / reload / unscope). The signature; use for most kills.
   - "clean": hit only, keeps momentum. Use in fast stretches and quiet sections.
   - "punch": hit + crash zoom, no slow-mo. Strong single kills in high-energy sections.
   - "cinematic": slow-mo + zoom + shake + edge-glow stylize. AT MOST 2 per montage:
     the best multi-kill or the single highest-impact play.
3. Match energy to the song: cinematic/punch where section energy is highest
   ("drop"/"chorus"); quieter sections get slow or clean.
4. Kills 1-2s apart are cut as one multi-kill clip; give the LAST kill of the best
   burst the cinematic treatment.
5. "scoped": true means a sniper kill; the engine adds a scope mask automatically.
   "flash_shake" suits scoped kills.
6. Excluding kills shortens the montage. Only prefer_exclude genuinely weak events.

Keep the reasoning field to 2-3 sentences describing your directorial intent."""


def _music_summary(beat_map: Any | None) -> dict[str, Any] | None:
    """Compact song description the director can actually reason about:
    tempo, section energy arc, and beat-accent statistics."""
    if beat_map is None:
        return None
    beats = list(getattr(beat_map, "beat_times", None) or [])
    strengths = list(getattr(beat_map, "beat_strengths", None) or [])
    sections = [
        {
            "start_sec": round(float(s.start_sec), 1),
            "end_sec": round(float(s.end_sec), 1),
            "type": str(s.section_type),
            "energy": round(float(s.avg_energy), 3),
        }
        for s in (getattr(beat_map, "sections", None) or [])
    ]
    strong_beats = sum(1 for s in strengths if float(s) >= 0.5)
    return {
        "tempo_bpm": round(float(getattr(beat_map, "tempo_bpm", 0.0) or 0.0), 1),
        "song_duration_sec": round(float(beats[-1]), 1) if beats else None,
        "total_beats": len(beats),
        "strong_accent_beats": strong_beats,
        "sections": sections,
    }


def build_user_prompt(*, enriched_events: list[EnrichedEvent], creative_config: dict[str, Any], beat_map: Any | None) -> str:
    # Keep prompt size controlled: include only top N events.
    top_n = 50
    events = enriched_events[:top_n]
    payload = {
        "creative_config": creative_config,
        "events": [
            {
                "idx": i,
                "video_index": e.event.video_index,
                "timestamp_sec": e.event.timestamp_sec,
                "score": e.event.score,
                "event_type": e.event.event_type,
                "gap_prev_sec": e.gap_prev_sec,
                "gap_next_sec": e.gap_next_sec,
                "multi_kill_group_id": e.multi_kill_group_id,
                "scoped": e.scoped,
            }
            for i, e in enumerate(events)
        ],
        "music": _music_summary(beat_map),
    }
    return "Produce a CreativeBrief JSON for this montage input:\n\n" + json.dumps(payload, indent=2)
