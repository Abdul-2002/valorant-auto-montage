from __future__ import annotations

from dataclasses import dataclass

from src.ai.schema import ScriptTransition
from src.pipeline.beat_analyzer import BeatMap


@dataclass(frozen=True)
class TransitionPlan:
    transitions_to_next: list[ScriptTransition | None]  # same length as clips, last is None


def _nearest_beat_index(t: float, beats: list[float]) -> int | None:
    if not beats:
        return None
    best_i = 0
    best_d = abs(float(t) - float(beats[0]))
    for i in range(1, len(beats)):
        d = abs(float(t) - float(beats[i]))
        if d < best_d:
            best_i = i
            best_d = d
    return best_i


def _section_type_at(beat_map: BeatMap | None, t: float) -> str | None:
    if beat_map is None or not getattr(beat_map, "sections", None):
        return None
    tt = float(t)
    for s in beat_map.sections:
        if float(s.start_sec) <= tt < float(s.end_sec):
            return str(s.section_type)
    return None


def plan_transitions(
    *,
    num_clips: int,
    beat_map: BeatMap | None,
    clip_output_starts_sec: list[float] | None = None,
    flash_frequency: float,
    outro_soft: bool = True,
) -> TransitionPlan:
    """
    Deterministic transition planner:
    - Default hard cuts
    - Insert flashes at roughly flash_frequency proportion, biased to downbeats when beat_map available
    """
    if num_clips <= 0:
        return TransitionPlan(transitions_to_next=[])

    flash_frequency = max(0.0, min(1.0, float(flash_frequency)))
    out: list[ScriptTransition | None] = []

    beats = list(beat_map.beat_times) if beat_map is not None else []
    # Simple deterministic pattern: every k-th transition is a flash, but if we have a beat grid,
    # prefer flashes on downbeats (every 4th beat).
    k = int(round(1.0 / flash_frequency)) if flash_frequency > 0 else 10**9
    clip_output_starts_sec = clip_output_starts_sec or []

    for i in range(num_clips):
        if i == num_clips - 1:
            out.append(None)
            continue

        # Soften the outro by forcing hard cuts late in montage.
        if outro_soft and i >= max(0, num_clips - 2):
            out.append(ScriptTransition(type="hard_cut", duration_sec=0.15))
            continue

        # Boundary time is next clip's output start (i+1). If unavailable, fall back to index pattern.
        boundary_t = None
        if i + 1 < len(clip_output_starts_sec):
            boundary_t = float(clip_output_starts_sec[i + 1])

        if beats and boundary_t is not None:
            bi = _nearest_beat_index(boundary_t, beats)
            is_downbeat = (bi is not None) and (bi % 4 == 0)
            stype = _section_type_at(beat_map, boundary_t)

            # Verse/intro/outro: prefer softer crossfades.
            if stype in ("verse", "intro", "outro"):
                out.append(ScriptTransition(type="dissolve", duration_sec=0.2))
            # Drops/chorus: accent downbeats with flash.
            elif stype in ("drop", "chorus") and is_downbeat and flash_frequency > 0:
                out.append(ScriptTransition(type="flash_white", duration_sec=0.05))
            else:
                out.append(ScriptTransition(type="hard_cut", duration_sec=0.15))
        else:
            if (i + 1) % max(1, k) == 0:
                out.append(ScriptTransition(type="flash_white", duration_sec=0.05))
            else:
                out.append(ScriptTransition(type="hard_cut", duration_sec=0.15))

    return TransitionPlan(transitions_to_next=out)
