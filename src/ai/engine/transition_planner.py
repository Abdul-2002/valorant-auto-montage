from __future__ import annotations

from dataclasses import dataclass

from src.ai.schema import ScriptTransition
from src.pipeline.beat_analyzer import BeatMap

HIGH_ENERGY = frozenset({"chorus", "drop", "inst", "solo"})
_ENERGY_ROTATION = ("zoom_in", "whip_pan", "spin", "hard_cut")
_CALM_ROTATION = ("hard_cut", "push", "hard_cut", "zoom_in")
_DURATIONS = {"flash_white": 0.05, "whip_pan": 0.14, "push": 0.12, "zoom_in": 0.14, "spin": 0.16, "hard_cut": 0.12}


@dataclass(frozen=True)
class TransitionPlan:
    transitions_to_next: list[ScriptTransition | None]  # same length as clips, last is None


def _section_type_at(beat_map: BeatMap | None, t: float) -> str:
    for s in (beat_map.sections if beat_map is not None else None) or []:
        if float(s.start_sec) <= float(t) < float(s.end_sec):
            return str(s.section_type)
    return ""


def _pick(boundary_label: str, prev_label: str, k: int, flash_ok: bool) -> str:
    if boundary_label != prev_label and boundary_label in HIGH_ENERGY and flash_ok:
        return "flash_white"
    if boundary_label in HIGH_ENERGY:
        return _ENERGY_ROTATION[k % len(_ENERGY_ROTATION)]
    return _CALM_ROTATION[k % len(_CALM_ROTATION)]


def plan_transitions(
    *,
    num_clips: int,
    beat_map: BeatMap | None,
    clip_output_starts_sec: list[float] | None = None,
    flash_frequency: float,
) -> TransitionPlan:
    """Section-aware transitions: flash into big sections, motion transitions inside them.

    The cut into the finale is always a zoom-through so the closing play lands hard.
    """
    if num_clips <= 0:
        return TransitionPlan(transitions_to_next=[])
    starts = clip_output_starts_sec or [float(i) for i in range(num_clips)]
    flash_ok = float(flash_frequency) > 0.0
    out: list[ScriptTransition | None] = []
    counters: dict[bool, int] = {True: 0, False: 0}
    for i in range(num_clips - 1):
        boundary = float(starts[i + 1]) if i + 1 < len(starts) else 0.0
        label = _section_type_at(beat_map, boundary)
        prev = _section_type_at(beat_map, float(starts[i]))
        if i == num_clips - 2:
            kind = "zoom_in"
        else:
            energy = label in HIGH_ENERGY
            kind = _pick(label, prev, counters[energy], flash_ok)
            counters[energy] += 1
        out.append(ScriptTransition(type=kind, duration_sec=_DURATIONS[kind]))
    out.append(None)
    return TransitionPlan(transitions_to_next=out)
