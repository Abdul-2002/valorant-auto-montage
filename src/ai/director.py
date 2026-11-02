from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from src.ai.enrichment import enrich_events
from src.ai.engine.composer import ComposeInputs, compose_script
from src.ai.engine.kill_grouping import build_play_flows
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
    from src.ai.engine.recommend import play_id
    from src.pipeline.types import DetectedEvent

    events = [DetectedEvent.model_validate(x) for x in highlights]
    enriched, durations = enrich_events(highlights=events, video_paths=video_paths)

    creative_cfg = resolve_creative_config(
        style_preset=config.ai_director.style_preset,
        creative_config=config.ai_director.creative_config.model_dump(mode="json"),
    )

    plays = build_play_flows(enriched)
    api_key = str(getattr(config.ai_director.gemini, "api_key", "") or "") or os.environ.get("GEMINI_API_KEY", "")
    # Always use Flash for play labels (not flash-lite director default).
    model = "gemini-2.5-flash"
    cache_path = (persist_path.parent / "play_labels.json") if persist_path is not None else None
    try:
        labeled = label_play_groups(
            plays,
            video_paths=video_paths,
            api_key=api_key,
            model=model,
            cache_path=cache_path,
        )
        n_lab = sum(1 for g in labeled if g.play_label)
        log.info("director: gemini play labels %d/%d", n_lab, len(labeled))
    except Exception:
        log.exception("director: play labeling failed; continuing unlabeled")
        labeled = plays

    # Studio selection locks the play set; composer still lays out + may soft-fit ceiling.
    use_flow_scoring = bool(getattr(config.ai_director, "use_flow_scoring", True))
    selection_locked = False
    if selected_play_ids:
        want = set(selected_play_ids)
        locked = [g for g in labeled if play_id(g) in want]
        if locked:
            labeled = locked
            use_flow_scoring = False
            selection_locked = True
            log.info("director: locked %d plays from studio selection", len(locked))

    duration_mode = str(getattr(config.output, "duration_mode", "fixed") or "fixed")
    curation_density = str(getattr(config.ai_director, "curation_density", "standard") or "standard")
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
            selection_locked=selection_locked,
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
