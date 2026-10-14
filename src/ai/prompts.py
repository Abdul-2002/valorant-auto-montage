from __future__ import annotations

import json
from typing import Any

from src.ai.enrichment import EnrichedEvent


SYSTEM_PROMPT = """You are a professional Valorant montage editor directing an editing engine.

You will be given:
- A ranked list of detected kills (scores, gaps, multi-kill groups, play labels)
- MUSIC CONTEXT: tempo, labeled song sections with energy, lyric/hook times
- A style configuration (creative_config)

You do NOT place clips on the timeline. The engine lands every kill on a beat and
cuts on bar boundaries. You decide HOW each kill should feel so the montage
breathes WITH the song instead of fighting it.

CRITICAL FLOW RULES (read carefully — bad flow is worse than no effects):
1. DEFAULT is "slow". Most kills should be "slow". Speed-up / punch is the exception.
2. NEVER alternate slow/punch/slow/punch just for variety. That reads as random and abrupt.
3. Match intensity to SONG ENERGY, not to kill index order:
   - High-energy sections (chorus / drop / inst / solo) OR near lyric hooks:
     prefer "punch" for sharp single taps, "slow" for stylish follow-through,
     "cinematic" only for the 1–2 peak plays.
   - Low-energy sections (intro / verse / bridge / outro):
     almost always "slow" or "clean". Do NOT assign "punch" here.
4. "clean" = hit only, keep momentum. Use for back-to-back filler kills in a fast
   stretch, or weak events you still keep. Never the montage's best kills.
5. "punch" = crash zoom, NO post-kill slow-mo. Use sparingly (roughly ≤25% of kills)
   on high-energy singles where a hard snap sells the beat. If unsure → "slow".
6. "cinematic" = slow-mo + zoom + shake + edge glow. HARD CAP: at most 2 per montage.
   Reserve for ACE / clutch / op / best multi-kill finale. Last kill of the best burst.
7. Multi-kills (gap < ~2s, shared multi_kill_group_id): treat as ONE phrase.
   Do not punch the first kill and slow the second randomly — keep the burst coherent
   (usually slow throughout, cinematic on the last kill of the best burst).

HIT STYLES (visible on the gun / kill frame — vary them, do not spam one):
- "glow": bloom biased to bright pixels / muzzle / skins. Default for rifle taps.
- "flash_blur": soft flash + lens blur. Use when the kill frame is already busy.
- "flash_shake": harder flash; engine adds camera shake. Prefer for Operator /
  shotgun / ACE / labeled clutch-op plays ("scoped": true → lean flash_shake).

OUTPUT REQUIREMENTS:
- Emit a "treatments" entry for EVERY event idx you keep (0..N-1 of the events list).
  Missing treatments fall back to a dumb mechanical rotation that ruins flow.
- Only prefer_exclude genuinely weak / duplicate events. Excluding shortens the cut.
- Keep reasoning to 2–3 sentences: describe the musical arc and where the peaks sit.

You are directing a song-led montage, not a highlight reel of equal clips."""


def _music_summary(
    beat_map: Any | None,
    *,
    enriched_events: list[EnrichedEvent] | None = None,
    lyric_events: list[tuple[float, str]] | None = None,
) -> dict[str, Any] | None:
    """Song context for the director.

    Important: kill timestamps are VOD source times, NOT song times. Do not label
    a kill with a song section by plugging source_sec into the song timeline —
    that lied to the model and produced random energy matching.
    """
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
    # High-energy windows the director should peak into (song time, not VOD time).
    peak_windows = [
        {"start_sec": s["start_sec"], "end_sec": s["end_sec"], "type": s["type"], "energy": s["energy"]}
        for s in sections
        if s["type"] in ("chorus", "drop", "inst", "solo") or float(s["energy"]) >= 0.55
    ]
    strong_beats = sum(1 for s in strengths if float(s) >= 0.5)
    # Kill quality context only — no fake song-section lookup from VOD timestamps.
    kill_music: list[dict[str, Any]] = []
    if enriched_events:
        for i, e in enumerate(enriched_events[:50]):
            kill_music.append(
                {
                    "event_idx": i,
                    "kill_src_sec": round(float(e.event.timestamp_sec), 2),
                    "score": round(float(e.event.score), 3),
                    "gap_prev_sec": round(float(e.gap_prev_sec), 2) if e.gap_prev_sec is not None else None,
                    "gap_next_sec": round(float(e.gap_next_sec), 2) if e.gap_next_sec is not None else None,
                    "multi_kill_group_id": e.multi_kill_group_id,
                    "scoped": bool(e.scoped),
                    "note": (
                        "Engine places this kill onto the song later. Choose recipe by "
                        "kill quality + desired song role (peak vs calm), not by source time."
                    ),
                }
            )
    lyrics = [
        {"at_sec": round(float(t), 2), "line": str(line)}
        for t, line in (lyric_events or [])[:16]
    ]
    return {
        "tempo_bpm": round(float(getattr(beat_map, "tempo_bpm", 0.0) or 0.0), 1),
        "song_duration_sec": round(float(beats[-1]), 1) if beats else None,
        "total_beats": len(beats),
        "strong_accent_beats": strong_beats,
        "sections": sections,
        "peak_windows": peak_windows,
        "kills": kill_music,
        "lyric_hooks": lyrics,
        "directing_hint": (
            "Put cinematic/punch intent on the highest-score / ACE / clutch kills so the "
            "engine can land them in peak_windows. Calm recipes for the rest."
        ),
    }


def build_user_prompt(
    *,
    enriched_events: list[EnrichedEvent],
    creative_config: dict[str, Any],
    beat_map: Any | None,
    lyric_events: list[tuple[float, str]] | None = None,
    play_labels: dict[int, str] | None = None,
) -> str:
    # Keep prompt size controlled: include only top N events.
    top_n = 50
    events = enriched_events[:top_n]
    payload: dict[str, Any] = {
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
                "play_label": (play_labels or {}).get(i, ""),
            }
            for i, e in enumerate(events)
        ],
        "music": _music_summary(beat_map, enriched_events=events, lyric_events=lyric_events),
        "requirements": {
            "treatments_must_cover_every_event_idx": True,
            "default_recipe": "slow",
            "max_cinematic": 2,
            "max_punch_fraction": 0.25,
            "no_mechanical_alternation": True,
        },
    }
    return (
        "Produce a CreativeBrief JSON for this montage input.\n"
        "Fill treatments for EVERY event idx. Prefer slow. Punch only on peaks.\n\n"
        + json.dumps(payload, indent=2)
    )
