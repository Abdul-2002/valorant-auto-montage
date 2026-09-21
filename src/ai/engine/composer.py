from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass

from src.ai.enrichment import EnrichedEvent
from src.ai.engine.arc_modeler import assign_arc_phases
from src.ai.engine.clip_selector import select_event_indices
from src.ai.engine.effect_mapper import EffectMappingInput, VALID_RECIPES, assign_recipes, map_effects
from src.ai.engine.timing import compute_clip_timing, align_kill_to_beat
from src.ai.engine.transition_planner import plan_transitions
from src.ai.schema import CreativeBrief, MontageScript, ScriptClip
from src.effects.presets.valorant import get_preset
from src.pipeline.beat_layout import layout_clips_on_beats
from src.pipeline.beat_analyzer import BeatMap

logger = logging.getLogger(__name__)

# Maximum playback speed that still looks intentional.  Anything above this
# compresses footage so fast it reads as a glitch rather than a style choice.
MAX_SPEED: float = 1.8

# Minimum playback speed. Below this footage is ultra-slow-motion and boring.
# If source footage is too short for the slot, we shrink the slot instead.
MIN_SPEED: float = 0.5

# Music timeline: used only for "was accent already near a grid beat?" logging.
BEAT_SNAP_TOLERANCE_SEC: float = 0.85


def _deduplicate_aligned_kills(events: list[EnrichedEvent], window_sec: float = 1.5) -> list[EnrichedEvent]:
    """Keep highest-score kill per source-timestamp window."""
    if not events:
        return []
    # Sort by source timestamp (seconds in video time domain).
    events_sorted = sorted(events, key=lambda e: float(e.event.timestamp_sec))
    kept: list[EnrichedEvent] = [events_sorted[0]]
    for evt in events_sorted[1:]:
        dt = float(evt.event.timestamp_sec) - float(kept[-1].event.timestamp_sec)
        if dt > float(window_sec):
            kept.append(evt)
        elif float(evt.event.score) > float(kept[-1].event.score):
            kept[-1] = evt
    return kept


def _snap_accent_to_nearest_beat_in_slot(
    accent: float,
    lo: float,
    hi: float,
    beats: list[float],
) -> tuple[float, bool]:
    """
    Snap output-timeline accent toward the nearest *music* beat. Always returns a time in [lo, hi].

    Prefer beats that fall inside this slot; if none, use globally nearest beat then clamp.
    `was_close` is True iff the snapped time is within BEAT_SNAP_TOLERANCE_SEC of `accent`.
    """
    if hi <= lo:
        return float(lo), False
    if not beats:
        a = max(lo, min(hi, float(accent)))
        return a, abs(a - accent) <= BEAT_SNAP_TOLERANCE_SEC

    in_slot = [b for b in beats if float(lo) <= float(b) <= float(hi)]
    pool = in_slot if in_slot else beats
    nearest = min(pool, key=lambda b: abs(float(b) - float(accent)))
    snapped = max(lo, min(hi, float(nearest)))
    was_close = abs(snapped - float(accent)) <= BEAT_SNAP_TOLERANCE_SEC
    return snapped, was_close


@dataclass(frozen=True)
class ComposeInputs:
    enriched_events: list[EnrichedEvent]
    beat_map: BeatMap | None
    creative_config_resolved: dict
    brief: CreativeBrief | None
    target_duration_sec: int


def compose_script(inp: ComposeInputs) -> MontageScript:
    n_beats = 0
    if inp.beat_map is not None and getattr(inp.beat_map, "beat_times", None):
        n_beats = len(inp.beat_map.beat_times or [])
    logger.info("composer: beat_map beat_times count=%d", n_beats)
    if n_beats >= 2:
        bt = sorted(float(x) for x in (inp.beat_map.beat_times or []))
        gaps = [bt[i + 1] - bt[i] for i in range(len(bt) - 1)]
        logger.info("composer: first 5 beats (song sec): %s", [round(x, 3) for x in bt[:5]])
        logger.info("composer: median beat interval: %.3fs", statistics.median(gaps))
    elif n_beats == 1:
        logger.info("composer: single beat only: %.3fs", float(inp.beat_map.beat_times[0]))

    # Estimate max clips from pacing: higher pacing => shorter clips => more clips.
    pacing = float(inp.creative_config_resolved.get("pacing", 0.8))
    avg_clip = 2.2 + (0.9 - 2.2) * max(0.0, min(1.0, pacing))
    max_events = max(1, min(60, int(max(5, inp.target_duration_sec) / max(0.5, avg_clip))))
    # Long targets need enough clips to fill ~45–120s output; ~2.5–4s of content per beat slot typical.
    if inp.target_duration_sec >= 45:
        max_events = max(max_events, min(45, max(12, int(inp.target_duration_sec / 2.8))))

    # Pro montage default: allow denser sequences without repeating the same moment.
    # Multi-kill bursts 1-2s apart are prime content; detector-level rising-edge
    # emission already suppresses phantom killfeed duplicates.
    diversity_sec = 2.0

    selection = select_event_indices(
        enriched=inp.enriched_events,
        brief=inp.brief,
        max_events=max_events,
        diversity_window_sec=diversity_sec,
    )
    selected = [inp.enriched_events[i] for i in selection.event_indices]
    selected = _deduplicate_aligned_kills(selected, window_sec=1.0)

    # Map original enriched-event indices to final clip indices so the
    # director's per-event treatments (special_treatments.event_idx) can be
    # applied after selection/dedup reordering. Identity-based: dedup keeps
    # the same EnrichedEvent objects.
    orig_idx_by_id = {id(e): i for i, e in enumerate(inp.enriched_events)}
    clip_idx_by_orig = {orig_idx_by_id[id(e)]: ci for ci, e in enumerate(selected) if id(e) in orig_idx_by_id}

    clips: list[ScriptClip] = []
    for i, ev in enumerate(selected):
        # Fixed source windows (Defectru-style): consistent rhythm in the source domain.
        # Beat sync happens in the output/music domain via beat slots + speed planning below.
        SOURCE_CLIP_DURATION = 3.2
        KILL_OFFSET = 1.6

        kill_t = float(ev.event.timestamp_sec)
        video_dur = float(ev.video_duration_sec or 0.0)

        start = max(0.0, kill_t - KILL_OFFSET)
        end = start + SOURCE_CLIP_DURATION

        # Clamp to [0, video_duration] to avoid negative indices / exceeding EOF.
        if video_dur > 0.0:
            start = max(0.0, min(start, video_dur))
            end = max(0.0, min(end, video_dur))
            # If clamping collapsed the window near EOF, pull start back.
            if (end - start) < 0.05:
                start = max(0.0, end - 0.05)
        clips.append(
            ScriptClip(
                video_index=int(ev.event.video_index),
                start_sec=float(start),
                end_sec=float(end),
                kill_timestamp_sec=float(kill_t),
                score=float(ev.event.score),
            )
        )

    # Beat-driven output layout: assign each clip an output slot on the music beat grid.
    pacing = float(inp.creative_config_resolved.get("pacing", 0.8))
    # Prefer starting the montage in a high-energy music section (chorus/drop)
    # so climax overlays land on the song's real accents, not the intro.
    start_beat = 0
    if inp.beat_map is not None and getattr(inp.beat_map, "sections", None) and inp.beat_map.beat_times:
        beats = list(inp.beat_map.beat_times)
        for sec in inp.beat_map.sections:
            if str(sec.section_type) in ("drop", "chorus"):
                t0 = float(sec.start_sec)
                # First beat at or after section start.
                for bi, b in enumerate(beats):
                    if float(b) >= t0:
                        start_beat = bi
                        break
                break

    layout = layout_clips_on_beats(
        beat_map=inp.beat_map,
        num_clips=len(clips),
        pacing=pacing,
        target_duration_sec=inp.target_duration_sec,
        max_slot_sec=3.75,
        start_at_beat_index=start_beat,
    )
    clip_output_starts = [float(s.output_start_sec) for s in layout.slots]

    phases = assign_arc_phases(
        num_clips=len(clips),
        brief=inp.brief,
        beat_map=inp.beat_map,
        clip_output_starts_sec=clip_output_starts,
    ).phases

    beat_times_sorted: list[float] = []
    if inp.beat_map is not None and getattr(inp.beat_map, "beat_times", None):
        beat_times_sorted = sorted(float(x) for x in (inp.beat_map.beat_times or []))

    # Per-clip effect recipes: director (brief) choices first, then budgeted
    # deterministic variety. This is what prevents "zoom on every kill".
    directed: dict[int, str] = {}
    if inp.brief is not None:
        for t in inp.brief.special_treatments or []:
            ci = clip_idx_by_orig.get(int(t.event_idx))
            if ci is not None and str(t.treatment) in VALID_RECIPES:
                directed[ci] = str(t.treatment)
    recipes = assign_recipes(
        scores=[float(c.score) for c in clips],
        phases=[str(p) for p in phases],
        directed=directed,
    )
    logger.info(
        "composer: effect recipes (director-set=%d): %s",
        len(directed),
        {r: recipes.count(r) for r in VALID_RECIPES},
    )

    aligned_clips = 0
    snap_close_count = 0

    for slot in layout.slots:
        if 0 <= slot.clip_index < len(clips):
            c = clips[slot.clip_index]
            out_dur = max(0.05, float(slot.output_end_sec) - float(slot.output_start_sec))
            src_dur = max(0.05, float(c.end_sec) - float(c.start_sec))

            # Compute raw speed needed to fit source into the beat slot.
            raw_speed = src_dur / out_dur

            if raw_speed > MAX_SPEED:
                # Trim the source window symmetrically around the kill timestamp
                # so it fits at MAX_SPEED instead of exceeding it.
                max_src_dur = out_dur * MAX_SPEED
                kill_rel = float(c.kill_timestamp_sec)
                # Proportion of kill within source clip.
                kill_frac = (kill_rel - float(c.start_sec)) / max(1e-9, src_dur)
                new_pre = max_src_dur * kill_frac
                new_post = max_src_dur * (1.0 - kill_frac)
                new_start = max(0.0, float(c.kill_timestamp_sec) - new_pre)
                new_end = float(c.kill_timestamp_sec) + new_post
                logger.warning(
                    "composer: speed %.2fx exceeds MAX_SPEED %.2fx for clip at %.1fs. "
                    "Trimming source %.2fs->%.2fs to %.2fs->%.2fs.",
                    raw_speed, MAX_SPEED, float(c.kill_timestamp_sec),
                    float(c.start_sec), float(c.end_sec), new_start, new_end,
                )
                c = c.model_copy(update={"start_sec": new_start, "end_sec": new_end})
                src_dur = max(0.05, new_end - new_start)
                speed = min(MAX_SPEED, src_dur / out_dur)
            else:
                speed = max(0.1, raw_speed)

            # MIN_SPEED guard: if footage would play too slow, shrink the output slot.
            if speed < MIN_SPEED:
                max_out_dur = src_dur / MIN_SPEED
                logger.warning(
                    "composer: speed %.2fx below MIN_SPEED %.2fx for clip at %.1fs. "
                    "Shrinking output slot from %.2fs to %.2fs.",
                    speed, MIN_SPEED, float(c.kill_timestamp_sec),
                    out_dur, max_out_dur,
                )
                out_dur = max_out_dur
                speed = MIN_SPEED

            phase = phases[slot.clip_index] if slot.clip_index < len(phases) else "build"
            beat_intensity = float(inp.creative_config_resolved.get("effect_intensity", 0.7))
            if inp.brief is not None and getattr(inp.brief, "intensity_bias", None) is not None:
                beat_intensity = float(inp.brief.intensity_bias)
            recipe = recipes[slot.clip_index] if slot.clip_index < len(recipes) else "clean"
            preset_for_beat = get_preset(str(phase), beat_intensity)
            # Slowmo consumption must match the velocity config emitted by
            # map_effects for this recipe, or the kill drifts off the accent.
            if recipe in ("clean", "punch"):
                slowmo_dur = 0.0
            else:
                slowmo_dur = float(preset_for_beat.velocity.get("kill_slowmo_duration_sec", 0.3))
            slowmo_fac = float(preset_for_beat.velocity.get("kill_slowmo_factor", 0.4))

            effects = map_effects(
                inp=EffectMappingInput(score=float(c.score), arc_phase=phase),
                creative_config=inp.creative_config_resolved,
                brief=inp.brief,
                recipe=recipe,
            )

            # Kill-on-beat alignment: compute per-clip pre/post speeds so the kill
            # frame arrives exactly at the accent beat within the slot.
            pre_kill_spd: float | None = None
            post_kill_spd: float | None = None
            kill_out_t: float | None = None
            accent_beat = float(getattr(slot, "accent_beat_sec", 0.0))
            lo_b = float(slot.output_start_sec)
            hi_b = float(slot.output_end_sec)
            if beat_times_sorted:
                accent_beat, was_snap_close = _snap_accent_to_nearest_beat_in_slot(
                    accent_beat, lo_b, hi_b, beat_times_sorted
                )
                if was_snap_close:
                    snap_close_count += 1
            else:
                accent_beat = max(lo_b, min(hi_b, accent_beat))

            src_kill_offset = float(c.kill_timestamp_sec) - float(c.start_sec)
            accent_in_slot = accent_beat - float(slot.output_start_sec)
            # Avoid exact 0 or out_dur: align_kill_to_beat divides by pre_out/post_out.
            eps = max(0.02, min(0.08, out_dur * 0.04))
            accent_in_slot = max(eps, min(out_dur - eps, accent_in_slot))

            if src_kill_offset > 0 and out_dur > eps * 3:
                pre_kill_spd, post_kill_spd, kill_out_t = align_kill_to_beat(
                    src_kill_offset=src_kill_offset,
                    src_duration=src_dur,
                    slot_duration=out_dur,
                    accent_offset_in_slot=accent_in_slot,
                    slowmo_duration=slowmo_dur,
                    slowmo_factor=slowmo_fac,
                )
                aligned_clips += 1

            clips[slot.clip_index] = c.model_copy(
                update={
                    "output_start_sec": float(slot.output_start_sec),
                    "output_end_sec": float(slot.output_start_sec) + out_dur,
                    "speed_factor": float(speed),
                    "arc_phase": phase,
                    "effects": effects,
                    "pre_kill_speed": pre_kill_spd,
                    "post_kill_speed": post_kill_spd,
                    "kill_output_time_sec": kill_out_t,
                }
            )

    logger.info(
        "composer: kill-on-beat alignment applied to %d/%d clips (accent snap within %.2fs for %d slots)",
        aligned_clips,
        len(clips),
        BEAT_SNAP_TOLERANCE_SEC,
        snap_close_count,
    )

    # Sanity-check total output duration before committing the script.
    total_output = sum(
        max(0.0, float(c.output_end_sec or 0.0) - float(c.output_start_sec or 0.0))
        for c in clips
    )
    lo = 0.5 * float(inp.target_duration_sec)
    hi = 2.0 * float(inp.target_duration_sec)
    if total_output < lo or total_output > hi:
        logger.error(
            "composer: total output duration %.1fs is outside acceptable range "
            "[%.1fs, %.1fs] for target=%ds. Script may produce garbage output.",
            total_output, lo, hi, inp.target_duration_sec,
        )

    transitions = plan_transitions(
        num_clips=len(clips),
        beat_map=inp.beat_map,
        clip_output_starts_sec=[float(c.output_start_sec or 0.0) for c in clips],
        flash_frequency=float(inp.creative_config_resolved.get("flash_frequency", 0.4)),
    ).transitions_to_next
    for i in range(len(clips)):
        tr = transitions[i] if i < len(transitions) else None
        if tr is not None:
            clips[i] = clips[i].model_copy(update={"transition_to_next": tr})

    return MontageScript(
        clips=clips or [ScriptClip(video_index=0, start_sec=0.0, end_sec=0.05, kill_timestamp_sec=0.0, score=0.0)],
        creative_config_resolved=dict(inp.creative_config_resolved),
        brief=inp.brief,
        reasoning=inp.brief.reasoning if inp.brief is not None else "",
    )
