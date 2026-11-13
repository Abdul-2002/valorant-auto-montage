from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from src.ai.enrichment import enrich_events
from src.ai.engine.composer import ComposeInputs, compose_script
from src.ai.engine.kill_grouping import build_play_flows
from src.ai.engine.kill_grouping import split_spectating_markers
from src.ai.engine.play_end import PlayEndConfig, collect_death_breaks
from src.ai.engine.recommend import resolve_locked_plays
from src.ai.play_labels import label_play_groups
from src.ai.presets import resolve_creative_config
from src.ai.schema import CreativeBrief, MontageScript
from src.ai.validation import validate_script
from src.config.models import AppConfig
from src.pipeline.beat_analyzer import BeatMap

log = logging.getLogger(__name__)


def generate_montage_script(
    *,
    highlights: list[dict[str, Any]],
    video_paths: list[Path],
    config: AppConfig,
    beat_map: BeatMap | None,
    brief: CreativeBrief | None = None,
    persist_path: Path | None = None,
    selected_play_ids: list[str] | None = None,
) -> tuple[MontageScript, list[float]]:
    from src.pipeline.types import DetectedEvent

    events = [DetectedEvent.model_validate(x) for x in highlights]
    enriched, durations = enrich_events(highlights=events, video_paths=video_paths)

    creative_cfg = resolve_creative_config(
        style_preset=config.ai_director.style_preset,
        creative_config=config.ai_director.creative_config.model_dump(mode="json"),
    )

    play_end_cfg = PlayEndConfig.model_validate(
        getattr(config.effects, "play_end", None).model_dump(mode="json")
        if getattr(config.effects, "play_end", None) is not None
        else {}
    )
    enriched, spectating_marks = split_spectating_markers(enriched)
    if spectating_marks:
        log.info("director: yolo spectating marks=%d", len(spectating_marks))

    kill_times: dict[int, list[float]] = {}
    for ev in enriched:
        kill_times.setdefault(int(ev.event.video_index), []).append(float(ev.event.timestamp_sec))

    death_breaks: tuple[tuple[int, float], ...] = tuple(spectating_marks)
    # Studio selections were built from unsplit plays. Re-scanning death between
    # kills rewrites play_ids, drops multis, and makes compose crawl on OneDrive.
    if play_end_cfg.enabled and not selected_play_ids:
        try:
            scanned = collect_death_breaks(
                kill_times_by_video=kill_times,
                video_paths=video_paths,
                cfg=play_end_cfg,
            )
            death_breaks = tuple(sorted({*death_breaks, *scanned}))
            log.info("director: death_breaks=%d", len(death_breaks))
        except Exception:
            log.exception("director: death-break scan failed; keeping YOLO spectating marks only")
    elif selected_play_ids:
        log.info("director: skipping death-break regroup; studio selection present")

    plays = build_play_flows(enriched, death_breaks=death_breaks)
    api_key = str(getattr(config.ai_director.gemini, "api_key", "") or "") or os.environ.get("GEMINI_API_KEY", "")
    # Always use Flash for play labels (not flash-lite director default).
    model = "gemini-2.5-flash"
    cache_path = (persist_path.parent / "play_labels.json") if persist_path is not None else None

    # Studio selection locks the play set; composer still lays out + may soft-fit ceiling.
    use_flow_scoring = bool(getattr(config.ai_director, "use_flow_scoring", True))
    selection_locked = False
    labeled = plays
    if selected_play_ids:
        # Exact play_id match fails after death-break splits; resolve by kill-set subset.
        locked = resolve_locked_plays(plays, selected_play_ids)
        if locked:
            labeled = locked
            use_flow_scoring = False
            selection_locked = True
            log.info(
                "director: locked %d plays / %d kills from studio selection (%d ids)",
                len(locked),
                sum(len(g.events) for g in locked),
                len(selected_play_ids),
            )
        else:
            log.warning(
                "director: studio selection matched 0 plays after grouping; falling back to curation"
            )

    # Skip Gemini labeling when selection is locked (labels unused) or when it would
    # block compose on a bad/missing API key across dozens of uploads.
    if os.environ.get("MONTAGE_SKIP_PLAY_LABELS", "").strip() == "1":
        log.info("director: play labeling skipped")
    elif not selection_locked:
        try:
            labeled = label_play_groups(
                labeled,
                video_paths=video_paths,
                api_key=api_key,
                model=model,
                cache_path=cache_path,
            )
            n_lab = sum(1 for g in labeled if g.play_label)
            log.info("director: gemini play labels %d/%d", n_lab, len(labeled))
        except Exception:
            log.exception("director: play labeling failed; continuing unlabeled")
    else:
        log.info("director: skipping play labeling for locked selection")

    duration_mode = str(getattr(config.output, "duration_mode", "fixed") or "fixed")
    # Locked studio picks drive bed length — don't pad/trim to a fixed song target.
    if selection_locked and duration_mode == "fixed":
        duration_mode = "clip_driven"
        log.info("director: selection_locked -> duration_mode=clip_driven")
    curation_density = str(getattr(config.ai_director, "curation_density", "standard") or "standard")
    recommend_max_plays = int(getattr(config.ai_director, "recommend_max_plays", 0) or 0)
    recommend_min_plays = int(getattr(config.ai_director, "recommend_min_plays", 12) or 12)
    raw = compose_script(
        ComposeInputs(
            enriched_events=enriched,
            beat_map=beat_map,
            creative_config_resolved=creative_cfg,
            brief=brief,
            target_duration_sec=int(config.output.target_duration_sec),
            velocity=config.effects.velocity,
            labeled_plays=labeled,
            duration_mode=duration_mode,
            curation_density=curation_density,
            use_flow_scoring=use_flow_scoring,
            recommend_max_plays=recommend_max_plays,
            recommend_min_plays=recommend_min_plays,
            selection_locked=selection_locked,
            video_paths=list(video_paths),
            play_end=play_end_cfg,
            death_breaks=death_breaks,
            gemini_api_key=api_key,
        )
    )

    validate_target = int(config.output.target_duration_sec)
    if duration_mode == "clip_driven" and raw.clips:
        # Compare against assembled length (sum of slots), not absolute song end time.
        validate_target = max(
            1,
            int(
                round(
                    sum(
                        max(0.0, float(c.output_end_sec or 0.0) - float(c.output_start_sec or 0.0))
                        for c in raw.clips
                    )
                )
            ),
        )
    fixed = validate_script(
        script=raw,
        enriched_events=enriched,
        video_durations_sec=durations,
        target_duration_sec=validate_target,
    )

    if persist_path is not None:
        persist_path.write_text(json.dumps(fixed.model_dump(mode="json"), indent=2), encoding="utf-8")

    return fixed, durations
