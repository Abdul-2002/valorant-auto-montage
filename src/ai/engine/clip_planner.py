"""Turn a kill group + its beat plan into a retimed, effect-mapped script clip."""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.ai.engine.effect_mapper import EffectMappingInput, map_effects, slowmo_params
from src.ai.engine.kill_grouping import KillGroup
from src.ai.schema import CreativeBrief, ScriptClip
from src.config.models import VelocityEffectConfig
from src.pipeline.beat_layout import ClipBeatPlan
from src.pipeline.time_remap import build_clip_remap, slowmo_factor_for_source


@dataclass(frozen=True)
class ClipDirection:
    recipe: str
    hit_style: str
    arc_phase: str
    pip_style: str = ""
    ghost_candidate: bool = False
    accent_beats: tuple[float, ...] = ()


def build_script_clip(
    *,
    group: KillGroup,
    plan: ClipBeatPlan,
    direction: ClipDirection,
    velocity: VelocityEffectConfig,
    creative_config: dict,
    brief: CreativeBrief | None,
) -> ScriptClip:
    slow_sec, target_factor = slowmo_params(recipe=direction.recipe, arc_phase=direction.arc_phase)
    factor = slowmo_factor_for_source(
        target=target_factor,
        source_fps=group.source_fps,
        min_unique_fps=float(velocity.slowmo_min_unique_fps),
    )
    kill_out_rel = [float(k) - plan.output_start_sec for k in plan.kill_output_sec]
    video_end = group.video_duration_sec if group.video_duration_sec > 0 else math.inf
    remap = build_clip_remap(
        out_duration=plan.duration_sec,
        kill_out=kill_out_rel,
        kill_src=group.kill_secs,
        src_bounds=(0.0, video_end),
        approach_speed=float(velocity.approach_speed),
        slowmo_out=slow_sec,
        slowmo_factor=factor,
        exit_speed=float(velocity.exit_speed),
    )
    effects = map_effects(
        inp=EffectMappingInput(score=group.score, arc_phase=direction.arc_phase),
        creative_config=creative_config,
        brief=brief,
        recipe=direction.recipe,
        hit_style=direction.hit_style,
        scoped=group.scoped,
        slowmo_factor=factor,
        pip_style=direction.pip_style,
    )
    return ScriptClip(
        video_index=group.video_index,
        start_sec=remap.src_start_sec,
        end_sec=remap.src_end_sec,
        kill_timestamp_sec=group.kill_secs[-1],
        kill_timestamps_sec=list(group.kill_secs),
        score=min(1.0, group.score),
        output_start_sec=plan.output_start_sec,
        output_end_sec=plan.output_end_sec,
        kill_output_times_sec=kill_out_rel,
        time_knots=remap.knots,
        recipe=direction.recipe,
        hit_style=direction.hit_style,
        scoped=group.scoped,
        accent_beats_sec=list(direction.accent_beats),
        pip_style=direction.pip_style,
        ghost_candidate=direction.ghost_candidate,
        effects=effects,
        arc_phase=direction.arc_phase,  # type: ignore[arg-type]
    )
