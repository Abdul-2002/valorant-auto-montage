from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.ai.enrichment import enrich_events
from src.ai.engine.composer import ComposeInputs, compose_script
from src.ai.presets import resolve_creative_config
from src.ai.schema import CreativeBrief, MontageScript
from src.ai.validation import validate_script
from src.config.models import AppConfig
from src.pipeline.beat_analyzer import BeatMap


def generate_montage_script(
    *,
    highlights: list[dict[str, Any]],
    video_paths: list[Path],
    config: AppConfig,
    beat_map: BeatMap | None,
    brief: CreativeBrief | None = None,
    persist_path: Path | None = None,
) -> tuple[MontageScript, list[float]]:
    dets = [h if hasattr(h, "timestamp_sec") else h for h in highlights]  # validated upstream; kept minimal here
    # Convert to DetectedEvent via MontageScript pipeline types isn't strictly needed here because
    # enrichment takes DetectedEvent; render_montage already normalizes. We'll reuse that shape later.
    from src.pipeline.types import DetectedEvent

    events = [DetectedEvent.model_validate(x) for x in highlights]
    enriched, durations = enrich_events(highlights=events, video_paths=video_paths)

    creative_cfg = resolve_creative_config(
        style_preset=config.ai_director.style_preset,
        creative_config=config.ai_director.creative_config.model_dump(mode="json"),
    )

    raw = compose_script(
        ComposeInputs(
            enriched_events=enriched,
            beat_map=beat_map,
            creative_config_resolved=creative_cfg,
            brief=brief,
            target_duration_sec=int(config.output.target_duration_sec),
        )
    )

    fixed = validate_script(
        script=raw,
        enriched_events=enriched,
        video_durations_sec=durations,
        target_duration_sec=int(config.output.target_duration_sec),
    )

    if persist_path is not None:
        persist_path.write_text(json.dumps(fixed.model_dump(mode="json"), indent=2), encoding="utf-8")

    return fixed, durations
