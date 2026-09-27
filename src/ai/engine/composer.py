from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.ai.enrichment import EnrichedEvent
from src.ai.engine.arc_modeler import assign_arc_phases
from src.ai.engine.clip_planner import ClipDirection, build_script_clip
from src.ai.engine.clip_selector import select_event_indices
from src.ai.engine.effect_mapper import VALID_RECIPES, assign_hit_styles, assign_recipes
from src.ai.engine.kill_grouping import KillGroup, fit_groups_to_duration, group_kills, move_finale_last
from src.ai.engine.transition_planner import plan_transitions
from src.ai.schema import CreativeBrief, MontageScript, ScriptClip
from src.config.models import VelocityEffectConfig
from src.pipeline.beat_analyzer import BeatMap
from src.pipeline.beat_layout import beat_interval, plan_kill_accents

logger = logging.getLogger(__name__)

# Candidate pool before grouping; the duration fit trims it afterwards.
MAX_CANDIDATE_EVENTS: int = 60
# Detector-level dedupe already merges killfeed flicker at 1.0s.
NEAR_DUP_WINDOW_SEC: float = 0.8
_RECIPE_PRIORITY = {r: i for i, r in enumerate(("clean", "slow", "punch", "cinematic"))}


@dataclass(frozen=True)
class ComposeInputs:
    enriched_events: list[EnrichedEvent]
    beat_map: BeatMap | None
    creative_config_resolved: dict
    brief: CreativeBrief | None
    target_duration_sec: int
    velocity: VelocityEffectConfig = field(default_factory=VelocityEffectConfig)


def _start_beat_index(beat_map: BeatMap | None, target_sec: float) -> int:
    """First beat of the first chorus/drop, pulled earlier if the song would run out."""
    if beat_map is None or not beat_map.beat_times:
        return 0
    beats = sorted(float(b) for b in beat_map.beat_times)
    start_t = 0.0
    for sec in beat_map.sections or []:
        if str(sec.section_type) in ("drop", "chorus"):
            start_t = float(sec.start_sec)
            break
    latest_start = max(0.0, beats[-1] - float(target_sec) * 1.1)
    start_t = min(start_t, latest_start)
    return next((i for i, b in enumerate(beats) if b >= start_t), 0)


def _directed_treatments(
    enriched: list[EnrichedEvent], groups: list[KillGroup], brief: CreativeBrief | None
) -> tuple[dict[int, str], dict[int, str]]:
    """Map director treatments (by enriched-event index) onto clip indices."""
    if brief is None:
        return {}, {}
    group_of = {id(e): gi for gi, g in enumerate(groups) for e in g.events}
    recipes: dict[int, str] = {}
    styles: dict[int, str] = {}
    for t in brief.special_treatments or []:
        idx = int(t.event_idx)
        if not 0 <= idx < len(enriched):
            continue
        gi = group_of.get(id(enriched[idx]))
        if gi is None:
            continue
        recipe = str(t.treatment)
        if recipe in VALID_RECIPES and _RECIPE_PRIORITY[recipe] >= _RECIPE_PRIORITY.get(recipes.get(gi, ""), -1):
            recipes[gi] = recipe
        if t.hit_style:
            styles[gi] = str(t.hit_style)
    return recipes, styles


def _select_groups(inp: ComposeInputs) -> list[KillGroup]:
    selection = select_event_indices(
        enriched=inp.enriched_events,
        brief=inp.brief,
        max_events=MAX_CANDIDATE_EVENTS,
        diversity_window_sec=0.0,
        near_dup_window_sec=NEAR_DUP_WINDOW_SEC,
    )
    selected = [inp.enriched_events[i] for i in selection.event_indices]
    interval = beat_interval(inp.beat_map, float(inp.target_duration_sec))
    groups = fit_groups_to_duration(
        group_kills(selected), target_sec=float(inp.target_duration_sec), beat_interval=interval
    )
    return move_finale_last(groups)


def _with_transitions(clips: list[ScriptClip], inp: ComposeInputs) -> list[ScriptClip]:
    transitions = plan_transitions(
        num_clips=len(clips),
        beat_map=inp.beat_map,
        clip_output_starts_sec=[float(c.output_start_sec or 0.0) for c in clips],
        flash_frequency=float(inp.creative_config_resolved.get("flash_frequency", 0.4)),
    ).transitions_to_next
    return [
        c.model_copy(update={"transition_to_next": transitions[i]}) if i < len(transitions) else c
        for i, c in enumerate(clips)
    ]


def compose_script(inp: ComposeInputs) -> MontageScript:
    groups = _select_groups(inp)
    plans = plan_kill_accents(
        beat_map=inp.beat_map,
        demands=[g.demand() for g in groups],
        target_duration_sec=float(inp.target_duration_sec),
        start_beat_index=_start_beat_index(inp.beat_map, float(inp.target_duration_sec)),
    )
    if len(plans) < len(groups):
        logger.warning("composer: song too short for %d clips; dropped %d", len(groups), len(groups) - len(plans))
    groups = groups[: len(plans)]
    phases = assign_arc_phases(
        num_clips=len(plans),
        brief=inp.brief,
        beat_map=inp.beat_map,
        clip_output_starts_sec=[p.output_start_sec for p in plans],
    ).phases
    directed_recipes, directed_styles = _directed_treatments(inp.enriched_events, groups, inp.brief)
    recipes = assign_recipes(scores=[g.score for g in groups], phases=phases, directed=directed_recipes)
    styles = assign_hit_styles(n=len(groups), directed=directed_styles)
    clips = [
        build_script_clip(
            group=g,
            plan=p,
            direction=ClipDirection(recipe=recipes[i], hit_style=styles[i], arc_phase=str(phases[i])),
            velocity=inp.velocity,
            creative_config=inp.creative_config_resolved,
            brief=inp.brief,
        )
        for i, (g, p) in enumerate(zip(groups, plans))
    ]
    logger.info(
        "composer: %d clips / %d kills, recipes=%s, scoped=%d, director-set=%d",
        len(clips),
        sum(len(c.kill_timestamps_sec) for c in clips),
        {r: recipes.count(r) for r in VALID_RECIPES},
        sum(1 for c in clips if c.scoped),
        len(directed_recipes),
    )
    clips = _with_transitions(clips, inp)
    return MontageScript(
        clips=clips or [ScriptClip(video_index=0, start_sec=0.0, end_sec=0.05, kill_timestamp_sec=0.0, score=0.0)],
        creative_config_resolved=dict(inp.creative_config_resolved),
        brief=inp.brief,
        reasoning=inp.brief.reasoning if inp.brief is not None else "",
    )
