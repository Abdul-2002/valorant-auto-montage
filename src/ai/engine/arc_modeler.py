from __future__ import annotations

from dataclasses import dataclass

from src.ai.schema import CreativeBrief, NarrativePhase
from src.pipeline.beat_analyzer import BeatMap


@dataclass(frozen=True)
class ArcPhaseAssignment:
    phases: list[str]  # same length as clips


def _phase_duration_pct(narc: dict, key: str, default: int) -> int:
    v = narc.get(key)
    if isinstance(v, NarrativePhase):
        return int(v.duration_pct)
    if isinstance(v, dict):
        return int(v.get("duration_pct", default))
    return default


def _phase_for_time(beat_map: BeatMap | None, t: float) -> str | None:
    if beat_map is None or not getattr(beat_map, "sections", None):
        return None
    tt = float(t)
    for s in beat_map.sections:
        if float(s.start_sec) <= tt < float(s.end_sec):
            st = str(s.section_type)
            if st in ("intro",):
                return "intro"
            if st in ("outro",):
                return "outro"
            if st in ("drop", "chorus"):
                return "climax"
            if st in ("verse",):
                return "build"
            return "build"
    return None


def assign_arc_phases(
    *,
    num_clips: int,
    brief: CreativeBrief | None,
    beat_map: BeatMap | None = None,
    clip_output_starts_sec: list[float] | None = None,
) -> ArcPhaseAssignment:
    if num_clips <= 0:
        return ArcPhaseAssignment(phases=[])

    if brief is not None and isinstance(brief.narrative_arc, str):
        hint = brief.narrative_arc.strip().lower()
        if hint in ("intro", "build", "climax", "outro"):
            return ArcPhaseAssignment(phases=[hint] * num_clips)

    # If we have music sections + output clip positions, map phases directly from music structure.
    if beat_map is not None and clip_output_starts_sec:
        phases: list[str] = []
        for i in range(num_clips):
            t = float(clip_output_starts_sec[i]) if i < len(clip_output_starts_sec) else 0.0
            p = _phase_for_time(beat_map, t) or "build"
            phases.append(p)
        return ArcPhaseAssignment(phases=phases[:num_clips])

    # Default percentages from the plan.
    intro_pct, build_pct, climax_pct, outro_pct = 15, 30, 40, 15
    if brief is not None and isinstance(brief.narrative_arc, dict) and brief.narrative_arc:
        narc = brief.narrative_arc
        intro_pct = _phase_duration_pct(narc, "intro", intro_pct)
        build_pct = _phase_duration_pct(narc, "build", build_pct)
        climax_pct = _phase_duration_pct(narc, "climax", climax_pct)
        outro_pct = _phase_duration_pct(narc, "outro", outro_pct)

    total = max(1, intro_pct + build_pct + climax_pct + outro_pct)
    intro_n = max(1, round(num_clips * intro_pct / total))
    build_n = max(1, round(num_clips * build_pct / total))
    climax_n = max(1, round(num_clips * climax_pct / total))
    outro_n = max(1, num_clips - (intro_n + build_n + climax_n))

    phases: list[str] = []
    phases.extend(["intro"] * intro_n)
    phases.extend(["build"] * build_n)
    phases.extend(["climax"] * climax_n)
    phases.extend(["outro"] * outro_n)
    return ArcPhaseAssignment(phases=phases[:num_clips])
