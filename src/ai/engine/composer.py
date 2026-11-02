from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from src.ai.enrichment import EnrichedEvent
from src.ai.engine.arc_modeler import assign_arc_phases
from src.ai.engine.clip_planner import ClipDirection, build_script_clip
from src.ai.engine.effect_mapper import VALID_RECIPES, assign_glitter_variants, assign_hit_styles, assign_recipes
from src.ai.engine.feature_budget import assign_features
from src.ai.engine.flow_scoring import pick_recommended
from src.ai.engine.kill_grouping import (
    HOLD_SCORE,
    KillGroup,
    build_play_flows,
    curate_plays,
    fit_groups_to_duration,
    with_locked_finale,
)
from src.ai.engine.transition_planner import plan_transitions
from src.ai.schema import CreativeBrief, MontageScript, ScriptClip
from src.config.models import VelocityEffectConfig
from src.pipeline.bar_layout import (
    BEATS_PER_BAR,
    bars_needed,
    estimate_montage_seconds,
    plan_on_bars,
    song_end_sec,
)
from src.pipeline.beat_analyzer import BeatMap
from src.pipeline.beat_layout import ClipBeatPlan, beat_interval, plan_kill_accents

logger = logging.getLogger(__name__)

# Detector-level dedupe already merges killfeed flicker at 1.0s; keep a tight
# collapse here so mid-ace kills are never treated as duplicates.
NEAR_DUP_WINDOW_SEC: float = 0.8
_RECIPE_PRIORITY = {r: i for i, r in enumerate(("clean", "slow", "punch", "cinematic"))}
# Sections where the camera pulses on strong beats between kills.
PULSE_SECTIONS = frozenset({"chorus", "drop", "inst", "solo", "climax"})
_PULSE_KILL_GUARD_SEC = 0.3


@dataclass(frozen=True)
class ComposeInputs:
    enriched_events: list[EnrichedEvent]
    beat_map: BeatMap | None
    creative_config_resolved: dict
    brief: CreativeBrief | None
    target_duration_sec: int
    velocity: VelocityEffectConfig = field(default_factory=VelocityEffectConfig)
    # Optional pre-labeled plays (Gemini). When set, selection uses these instead of rebuilding.
    labeled_plays: list[KillGroup] | None = None
    # "fixed" = pack into target_duration_sec / full bed; "clip_driven" = bed follows curated plays.
    duration_mode: str = "fixed"
    # "standard" = multis + strong/labeled singles; "dense" = multis + ace/clutch singles only.
    curation_density: str = "standard"
    use_flow_scoring: bool = True
    # Studio confirmed set — do not re-drop plays in curate_plays.
    selection_locked: bool = False


def _bar_mode(beat_map: BeatMap | None) -> bool:
    return beat_map is not None and len(beat_map.downbeat_times or []) >= 3


def _start_beat_index(beat_map: BeatMap | None, target_sec: float) -> int:
    """Start at song t=0 so intro/build-up is heard; clamp only if the track is too short."""
    if beat_map is None or not beat_map.beat_times:
        return 0
    beats = sorted(float(b) for b in beat_map.beat_times)
    # Keep the cold-open at the start. Chorus alignment is handled by bar_layout
    # (lead-in clips before the first chorus) when downbeats exist.
    start_t = 0.0
    if beats[-1] < float(target_sec) * 1.1:
        start_t = max(0.0, beats[-1] - float(target_sec) * 1.1)
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
        gi = group_of.get(id(enriched[idx])) if 0 <= idx < len(enriched) else None
        if gi is None:
            continue
        recipe = str(t.treatment)
        if recipe in VALID_RECIPES and _RECIPE_PRIORITY[recipe] >= _RECIPE_PRIORITY.get(recipes.get(gi, ""), -1):
            recipes[gi] = recipe
        if t.hit_style:
            styles[gi] = str(t.hit_style)
    return recipes, styles


def select_kill_groups(
    *,
    enriched: list[EnrichedEvent],
    brief: CreativeBrief | None,
    beat_map: BeatMap | None,
    target_sec: float,
    labeled_plays: list[KillGroup] | None = None,
    duration_mode: str = "fixed",
    curation_density: str = "standard",
    use_flow_scoring: bool = True,
    selection_locked: bool = False,
) -> list[KillGroup]:
    """Build continuous plays, keep the most impactful ones, finale = biggest multi-kill.

    Flow (production):
    1. Collapse killfeed flicker only (or use pre-labeled Gemini plays).
    2. Form full same-VOD multi-kill runs (ace/quadra as one clip, first→last).
    3. Curate by Gemini label + score (or flow scoring); drop junk even if bed fits.
    4. Impact-rising body + locked impact finale.

    ``clip_driven``: ``target_sec`` is a soft ceiling (not a fill target). Bed length
    is derived later from the kept plays' natural bar needs.
    """
    del brief  # Director brief is optional; labels live on KillGroup.play_label.
    plays = list(labeled_plays) if labeled_plays is not None else build_play_flows(enriched, near_dup_sec=NEAR_DUP_WINDOW_SEC)
    interval = beat_interval(beat_map, target_sec)
    clip_driven = str(duration_mode) == "clip_driven"
    if selection_locked and plays:
        ordered = with_locked_finale(plays)
        budget = float(target_sec)
        if _bar_mode(beat_map):
            bar_sec = BEATS_PER_BAR * interval
            budget = float(target_sec) if clip_driven else (song_end_sec(beat_map) - float(beat_map.downbeat_times[0]))
            ordered = fit_groups_to_duration(
                ordered,
                target_sec=budget,
                beat_interval=interval,
                min_clip_sec=lambda g: bars_needed(g.demand(), interval) * bar_sec,
            )
        else:
            ordered = fit_groups_to_duration(ordered, target_sec=budget, beat_interval=interval)
    elif _bar_mode(beat_map):
        bar_sec = BEATS_PER_BAR * interval
        # Fixed mode may use the full bed as the fit budget; clip_driven uses the ceiling only.
        budget = float(target_sec) if clip_driven else (song_end_sec(beat_map) - float(beat_map.downbeat_times[0]))
        min_clip = lambda g: bars_needed(g.demand(), interval) * bar_sec
        if use_flow_scoring:
            picked = pick_recommended(plays, max_plays=16, density=str(curation_density))
            kept = fit_groups_to_duration(
                picked, target_sec=budget, beat_interval=interval, min_clip_sec=min_clip
            )
            ordered = kept
        else:
            kept = curate_plays(
                plays,
                target_sec=budget,
                beat_interval=interval,
                min_clip_sec=min_clip,
                density=str(curation_density),
                clip_driven=clip_driven,
            )
            ordered = with_locked_finale(kept)
    else:
        if use_flow_scoring:
            picked = pick_recommended(plays, max_plays=16, density=str(curation_density))
            ordered = fit_groups_to_duration(picked, target_sec=target_sec, beat_interval=interval)
        else:
            kept = curate_plays(
                plays,
                target_sec=target_sec,
                beat_interval=interval,
                density=str(curation_density),
                clip_driven=clip_driven,
            )
            ordered = with_locked_finale(kept)
    logger.info(
        "composer: selected %d plays (%d kills) finale=%d-kill labels=%s mode=%s density=%s",
        len(ordered),
        sum(len(g.events) for g in ordered),
        len(ordered[-1].events) if ordered else 0,
        dict(Counter(g.play_label or "unlabeled" for g in ordered)),
        duration_mode,
        curation_density,
    )
    return ordered


def _plan(inp: ComposeInputs, groups: list[KillGroup]) -> list[ClipBeatPlan]:
    demands = [g.demand() for g in groups]
    if _bar_mode(inp.beat_map):
        end = song_end_sec(inp.beat_map)
        start_at_zero = False
        if str(inp.duration_mode) == "clip_driven":
            interval = beat_interval(inp.beat_map, float(inp.target_duration_sec))
            bed = estimate_montage_seconds(demands, beat_interval=interval)
            # Small pad so allocate_bars/grow + post-kill room do not clip the finale.
            bed = bed + (BEATS_PER_BAR * interval)
            end = min(end, max(bed, interval * BEATS_PER_BAR * 2), float(inp.target_duration_sec))
            start_at_zero = True
            logger.info(
                "composer: clip_driven bed %.1fs (ceiling %.1fs, song %.1fs)",
                end,
                float(inp.target_duration_sec),
                song_end_sec(inp.beat_map),
            )
        return plan_on_bars(
            beat_map=inp.beat_map,
            demands=demands,
            song_end_sec=end,
            start_at_zero=start_at_zero,
        )
    plan_target = float(inp.target_duration_sec)
    if str(inp.duration_mode) == "clip_driven":
        interval = beat_interval(inp.beat_map, plan_target)
        plan_target = min(plan_target, estimate_montage_seconds(demands, beat_interval=interval))
    return plan_kill_accents(
        beat_map=inp.beat_map,
        demands=demands,
        target_duration_sec=plan_target,
        start_beat_index=_start_beat_index(inp.beat_map, plan_target),
    )


def _accent_beats(beat_map: BeatMap | None, plan: ClipBeatPlan) -> list[float]:
    """Clip-relative strong beats in high-energy sections, away from the kills (camera pulses)."""
    if beat_map is None or not beat_map.beat_times or not beat_map.beat_strengths:
        return []
    strengths = np.asarray(beat_map.beat_strengths, dtype=np.float64)
    thr = max(0.55, float(np.percentile(strengths, 70.0)))
    out: list[float] = []
    for b, s in zip(beat_map.beat_times, strengths):
        if not plan.output_start_sec < b < plan.output_end_sec or s < thr:
            continue
        if any(abs(b - k) < _PULSE_KILL_GUARD_SEC for k in plan.kill_output_sec):
            continue
        label = next((x.section_type for x in beat_map.sections if x.start_sec <= b < x.end_sec), "")
        if label in PULSE_SECTIONS:
            out.append(float(b) - plan.output_start_sec)
    return out


def _with_transitions(clips: list[ScriptClip], inp: ComposeInputs) -> list[ScriptClip]:
    transitions = plan_transitions(
        num_clips=len(clips),
        beat_map=inp.beat_map,
        clip_output_starts_sec=[float(c.output_start_sec or 0.0) for c in clips],
        flash_frequency=float(inp.creative_config_resolved.get("flash_frequency", 0.4)),
        clip_sources=[(c.video_index, float(c.kill_timestamp_sec)) for c in clips],
        scene_jigsaw=str(inp.creative_config_resolved.get("style_fx", "")) == "reference",
        beat_interval_sec=beat_interval(inp.beat_map),
        jigsaw_ranks=[
            2 if len(c.kill_timestamps_sec) >= 2 else (1 if float(c.score) >= HOLD_SCORE else 0) for c in clips
        ],
    ).transitions_to_next
    return [
        c.model_copy(update={"transition_to_next": transitions[i]}) if i < len(transitions) else c
        for i, c in enumerate(clips)
    ]


def compose_script(inp: ComposeInputs) -> MontageScript:
    groups = select_kill_groups(
        enriched=inp.enriched_events,
        brief=inp.brief,
        beat_map=inp.beat_map,
        target_sec=float(inp.target_duration_sec),
        labeled_plays=inp.labeled_plays,
        duration_mode=str(inp.duration_mode),
        curation_density=str(inp.curation_density),
        use_flow_scoring=bool(inp.use_flow_scoring),
        selection_locked=bool(inp.selection_locked),
    )
    plans = _plan(inp, groups)
    if len(plans) < len(groups):
        dropped = len(groups) - len(plans)
        logger.warning("composer: song too short for %d clips; dropped %d from body (keep finale)", len(groups), dropped)
        # Never truncate the locked finale — drop weakest body plays instead.
        if len(plans) >= 1 and len(groups) >= 2:
            body = list(groups[:-1])
            finale = groups[-1]
            keep_body = max(0, len(plans) - 1)
            # body is rising-impact ordered; drop from the front (weakest).
            groups = body[len(body) - keep_body :] + [finale] if keep_body else [finale]
            plans = _plan(inp, groups)
            if len(plans) < len(groups):
                groups = groups[: len(plans)]
        else:
            groups = groups[: len(plans)]
    phases = assign_arc_phases(
        num_clips=len(plans), brief=inp.brief, beat_map=inp.beat_map, clip_output_starts_sec=[p.output_start_sec for p in plans]
    ).phases
    directed_recipes, directed_styles = _directed_treatments(inp.enriched_events, groups, inp.brief)
    recipes = assign_recipes(scores=[g.score for g in groups], phases=phases, directed=directed_recipes)
    styles = assign_hit_styles(
        n=len(groups),
        directed=directed_styles,
        style_fx=str(inp.creative_config_resolved.get("style_fx", "")),
    )
    glitter = assign_glitter_variants(len(groups))
    features = assign_features(
        recipes=recipes,
        kill_counts=[len(g.events) for g in groups],
        scores=[g.score for g in groups],
        style_fx=str(inp.creative_config_resolved.get("style_fx", "")),
    )
    clips = [
        build_script_clip(
            group=g,
            plan=p,
            direction=ClipDirection(
                recipe=recipes[i],
                hit_style=styles[i],
                arc_phase=str(phases[i]),
                pip_style=features[i].pip_style,
                ghost_candidate=features[i].ghost_candidate,
                gun_candidate=features[i].gun_candidate,
                accent_beats=tuple(_accent_beats(inp.beat_map, p)),
                glitter_variant=glitter[i],
            ),
            velocity=inp.velocity,
            creative_config=inp.creative_config_resolved,
            brief=inp.brief,
        )
        for i, (g, p) in enumerate(zip(groups, plans))
    ]
    logger.info(
        "composer: %d clips / %d kills (bar_mode=%s), recipes=%s, pip=%d, ghost_candidates=%d, director-set=%d",
        len(clips),
        sum(len(c.kill_timestamps_sec) for c in clips),
        _bar_mode(inp.beat_map),
        {r: recipes.count(r) for r in VALID_RECIPES},
        sum(1 for f in features if f.pip_style),
        sum(1 for f in features if f.ghost_candidate),
        len(directed_recipes),
    )
    clips = _with_transitions(clips, inp)
    return MontageScript(
        clips=clips or [ScriptClip(video_index=0, start_sec=0.0, end_sec=0.05, kill_timestamp_sec=0.0, score=0.0)],
        creative_config_resolved=dict(inp.creative_config_resolved),
        brief=inp.brief,
        reasoning=inp.brief.reasoning if inp.brief is not None else "",
    )
