from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.ai.schema import ScriptTransition
from src.pipeline.beat_analyzer import BeatMap

HIGH_ENERGY = frozenset({"chorus", "drop", "inst", "solo"})
# zoom_in and spin have no assembler branch, so a chorus cut would be a raw join.
_ENERGY_ROTATION = ("whip_pan", "pop_slam", "push", "pop_slam")
# hard_cut is a raw concatenate, so calm sections use a short motion bridge instead.
_CALM_ROTATION = ("whip_pan", "push", "whip_pan", "pop_slam")
_DURATIONS = {
    "flash_white": 0.05,
    "whip_pan": 0.14,
    "push": 0.12,
    "zoom_in": 0.14,
    "spin": 0.16,
    "hard_cut": 0.12,
    "pop_slam": 0.22,
}

MAX_SCENE_JIGSAWS = 2
# Same-VOD kills this far apart are different rounds, so the incoming elements differ.
_NEW_SCENE_GAP_SEC = 30.0
_FALLBACK_BEAT_SEC = 0.43


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


def _is_new_scene(a: tuple[int, float], b: tuple[int, float]) -> bool:
    return a[0] != b[0] or abs(float(b[1]) - float(a[1])) >= _NEW_SCENE_GAP_SEC


def _jigsaw_too_close(cut: int, taken: Sequence[int], ranks: Sequence[int] | None) -> bool:
    """True when a jigsaw here would stack onto a short clip.

    A multi-kill is long enough that its entrance and the finale jigsaw can both play.
    """
    for other in taken:
        if abs(cut - other) >= 2:
            continue
        sandwiched = max(cut, other)
        if ranks is not None and sandwiched < len(ranks) and int(ranks[sandwiched]) >= 2:
            continue
        return True
    return False


def scene_jigsaw_slots(
    kinds: list[str],
    clip_sources: list[tuple[int, float]],
    ranks: Sequence[int] | None = None,
) -> set[int]:
    """Up to two jigsaws on scene changes into a hold or a multi-kill.

    ``ranks[i]`` is 2 for a multi-kill, 1 for a hold, 0 for a kill-only clip.
    A missing rank treats every incoming clip as eligible. Never a flash cut,
    and never next to another jigsaw. The finale jigsaw is already in ``kinds``.
    """
    taken = [i for i, k in enumerate(kinds) if k == "jigsaw"]
    candidates: list[int] = []
    for i in range(len(kinds) - 1):
        if kinds[i] in ("flash_white", "jigsaw") or i + 1 >= len(clip_sources):
            continue
        if ranks is not None and (i + 1 >= len(ranks) or int(ranks[i + 1]) <= 0):
            continue
        if not _is_new_scene(clip_sources[i], clip_sources[i + 1]):
            continue
        if _jigsaw_too_close(i, taken, ranks):
            continue
        candidates.append(i)
    candidates.sort(key=lambda i: (-(int(ranks[i + 1]) if ranks is not None else 1), i))
    picked: list[int] = []
    for i in candidates:
        if len(picked) >= MAX_SCENE_JIGSAWS:
            break
        if _jigsaw_too_close(i, taken + picked, ranks):
            continue
        picked.append(i)
    return set(picked)


def plan_transitions(
    *,
    num_clips: int,
    beat_map: BeatMap | None,
    clip_output_starts_sec: list[float] | None = None,
    flash_frequency: float,
    clip_sources: list[tuple[int, float]] | None = None,
    scene_jigsaw: bool = False,
    beat_interval_sec: float | None = None,
    jigsaw_ranks: Sequence[int] | None = None,
) -> TransitionPlan:
    """Section-aware transitions: flash into big sections, motion transitions inside them.

    The cut into the finale is always a jigsaw so the closing play lands hard.
    Jigsaws span one beat (``beat_interval_sec``).
    Reference style adds at most two more, and only into a hold or a multi-kill.
    """
    if num_clips <= 0:
        return TransitionPlan(transitions_to_next=[])
    starts = clip_output_starts_sec or [float(i) for i in range(num_clips)]
    flash_ok = float(flash_frequency) > 0.0
    kinds: list[str] = []
    counters: dict[bool, int] = {True: 0, False: 0}
    for i in range(num_clips - 1):
        boundary = float(starts[i + 1]) if i + 1 < len(starts) else 0.0
        label = _section_type_at(beat_map, boundary)
        prev = _section_type_at(beat_map, float(starts[i]))
        if i == num_clips - 2:
            kinds.append("jigsaw")
            continue
        energy = label in HIGH_ENERGY
        kind = _pick(label, prev, counters[energy], flash_ok)
        counters[energy] += 1
        kinds.append("pop_slam" if kind == "jigsaw" and i == num_clips - 3 else kind)
    if scene_jigsaw and clip_sources:
        for i in scene_jigsaw_slots(kinds, clip_sources, jigsaw_ranks):
            kinds[i] = "jigsaw"
    beat = float(beat_interval_sec or _FALLBACK_BEAT_SEC)
    out: list[ScriptTransition | None] = [
        ScriptTransition(type=kind, duration_sec=beat if kind == "jigsaw" else _DURATIONS[kind]) for kind in kinds
    ]
    out.append(None)
    return TransitionPlan(transitions_to_next=out)
