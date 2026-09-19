from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.app.dependencies import get_storage_dir
from src.config.loader import _deep_merge
from src.config.models import AppConfig
from src.ai.director import generate_montage_script
from src.ai.schema import CreativeBrief
from src.ai.enrichment import enrich_events
from src.ai.providers import safe_generate_brief
from src.ai.providers.base import BriefContext
from src.pipeline.beat_analyzer import analyze_beats
from src.pipeline.highlight_detector import detect_highlights
from src.pipeline.montage_assembler import render_montage
from src.worker.celery_app import celery_app


def _task_dir(task_id: str) -> Path:
    return get_storage_dir() / "tasks" / task_id


@celery_app.task(bind=True)
def detect_highlights_task(self, payload: dict[str, Any]) -> dict[str, Any]:
    task_id = self.request.id
    tdir = _task_dir(task_id)
    tdir.mkdir(parents=True, exist_ok=True)

    self.update_state(state="PROGRESS", meta={"phase": "loading_inputs", "progress": 0.05, "task_id": task_id})

    meta_path = tdir / "meta.json"
    if not meta_path.exists():
        raise RuntimeError("meta.json missing (upload not completed?)")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    config = AppConfig.model_validate(payload.get("config", {}))
    (tdir / "detect_config.json").write_text(config.model_dump_json(indent=2), encoding="utf-8")
    self.update_state(state="PROGRESS", meta={"phase": "detecting", "progress": 0.15})

    highlights = detect_highlights(
        video_paths=[Path(p) for p in meta["videos"]],
        config=config,
        task_progress_cb=lambda p: self.update_state(state="PROGRESS", meta={"phase": "detecting", "progress": p}),
    )

    out_path = tdir / "highlights.json"
    out_path.write_text(json.dumps({"highlights": [h.model_dump(mode="json") for h in highlights]}, indent=2), encoding="utf-8")

    return {"task_id": task_id, "phase": "review_ready", "progress": 1.0, "num_highlights": len(highlights)}


@celery_app.task(bind=True)
def render_montage_task(self, payload: dict[str, Any]) -> dict[str, Any]:
    detect_task_id = payload["detect_task_id"]
    tdir = _task_dir(detect_task_id)

    confirmed_path = tdir / "confirmed.json"
    if not confirmed_path.exists():
        raise RuntimeError("confirmed.json missing")

    meta_path = tdir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    config_path = payload.get("config_path")
    if config_path:
        config = AppConfig.model_validate(json.loads(Path(config_path).read_text(encoding="utf-8")))
    else:
        # reuse config stored in detect payload if present, else fall back to default.yaml loaded by API
        detect_cfg = (tdir / "detect_config.json")
        config = AppConfig.model_validate(json.loads(detect_cfg.read_text(encoding="utf-8"))) if detect_cfg.exists() else AppConfig()

    confirmed = json.loads(confirmed_path.read_text(encoding="utf-8"))
    overrides = confirmed.get("overrides") or {}
    if overrides:
        merged = config.model_dump(mode="json")
        merged = _deep_merge(merged, overrides)
        config = AppConfig.model_validate(merged)

    self.update_state(state="PROGRESS", meta={"phase": "rendering", "progress": 0.05, "task_id": detect_task_id})

    out_dir = tdir / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    # BeatMap: used by the director (beat layout, transitions, brief). The renderer aligns
    # music to script output_start_sec in montage_assembler when all clips carry output fields.
    beat_map = None
    try:
        if meta.get("music"):
            beat_map = analyze_beats(Path(meta["music"]))
    except Exception:
        beat_map = None

    script_path = tdir / "montage_script.json"

    # If the user posted a custom script via POST /script, prefer it.
    if script_path.exists():
        from src.ai.schema import MontageScript

        script = MontageScript.model_validate(json.loads(script_path.read_text(encoding="utf-8")))
    else:
        # AI Director: generate a montage_script.json and render from it.
        # Provider failures should never fail the render; brief falls back to None.
        brief: CreativeBrief | None = None
        try:
            from src.pipeline.types import DetectedEvent

            events = [DetectedEvent.model_validate(x) for x in confirmed["highlights"]]
            enriched, _durations = enrich_events(highlights=events, video_paths=[Path(p) for p in meta["videos"]])
            creative_cfg = config.ai_director.creative_config.model_dump(mode="json")
            brief = safe_generate_brief(
                cfg=config.ai_director,
                ctx=BriefContext(enriched_events=enriched, beat_map=beat_map, creative_config_resolved=creative_cfg),
            )
        except Exception:
            brief = None

        script, _durations = generate_montage_script(
            highlights=confirmed["highlights"],
            video_paths=[Path(p) for p in meta["videos"]],
            config=config,
            beat_map=beat_map,
            brief=brief,
            persist_path=script_path,
        )

    render_montage(
        video_paths=[Path(p) for p in meta["videos"]],
        music_path=Path(meta["music"]) if meta.get("music") else None,
        highlights=confirmed["highlights"],
        config=config,
        out_dir=out_dir,
        script=script,
        task_progress_cb=lambda p: self.update_state(state="PROGRESS", meta={"phase": "rendering", "progress": p}),
    )

    return {"detect_task_id": detect_task_id, "phase": "complete", "progress": 1.0, "outputs_dir": str(out_dir)}
