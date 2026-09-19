#!/usr/bin/env python3
"""Run detect → compose script → render without Celery (local smoke / integration test)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from src.ai.director import generate_montage_script
from src.ai.enrichment import enrich_events
from src.ai.providers import safe_generate_brief
from src.ai.providers.base import BriefContext
from src.config.loader import load_config
from src.pipeline.beat_analyzer import analyze_beats
from src.pipeline.highlight_detector import detect_highlights
from src.pipeline.montage_assembler import render_montage
from src.pipeline.types import DetectedEvent


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Local end-to-end montage pipeline")
    p.add_argument("--video", required=True, type=Path, help="Gameplay video path")
    p.add_argument("--music", required=True, type=Path, help="Music track path")
    p.add_argument("--out", type=Path, default=ROOT / "artifacts/local_pipeline_run", help="Output directory")
    p.add_argument("--config", type=Path, default=ROOT / "config/default.yaml")
    args = p.parse_args()

    video = args.video.resolve()
    music = args.music.resolve()
    out = args.out.resolve()
    if not video.is_file():
        print(f"Video not found: {video}", file=sys.stderr)
        return 1
    if not music.is_file():
        print(f"Music not found: {music}", file=sys.stderr)
        return 1

    out.mkdir(parents=True, exist_ok=True)
    cfg_path = args.config if args.config.is_file() else ROOT / args.config
    config = load_config(cfg_path)

    print("Phase: highlight detection (auto_gaming_yolo + audio_peaks)...", flush=True)
    highlights = detect_highlights(video_paths=[video], config=config)
    print(f"  -> {len(highlights)} events", flush=True)

    hl_json = [h.model_dump(mode="json") for h in highlights]
    (out / "highlights.json").write_text(json.dumps({"highlights": hl_json}, indent=2), encoding="utf-8")
    (out / "confirmed.json").write_text(
        json.dumps({"highlights": hl_json, "overrides": {}}, indent=2),
        encoding="utf-8",
    )

    beat_map = None
    print("Phase: beat analysis...", flush=True)
    try:
        beat_map = analyze_beats(music)
        print(f"  -> tempo ~{getattr(beat_map, 'tempo_bpm', None)} bpm", flush=True)
    except Exception as exc:
        print(f"  -> skipped: {exc}", flush=True)

    brief = None
    try:
        events = [DetectedEvent.model_validate(x) for x in hl_json]
        enriched, _durations = enrich_events(highlights=events, video_paths=[video])
        creative_cfg = config.ai_director.creative_config.model_dump(mode="json")
        brief = safe_generate_brief(
            cfg=config.ai_director,
            ctx=BriefContext(enriched_events=enriched, beat_map=beat_map, creative_config_resolved=creative_cfg),
        )
    except Exception as exc:
        print(f"Brief generation skipped: {exc}", flush=True)

    script_path = out / "montage_script.json"
    print("Phase: compose script...", flush=True)
    script, _ = generate_montage_script(
        highlights=hl_json,
        video_paths=[video],
        config=config,
        beat_map=beat_map,
        brief=brief,
        persist_path=script_path,
    )
    print(f"  -> {len(script.clips)} clips", flush=True)

    render_out = out / "outputs"
    render_out.mkdir(parents=True, exist_ok=True)
    print("Phase: render (MoviePy + ffmpeg)...", flush=True)
    render_montage(
        video_paths=[video],
        music_path=music,
        highlights=hl_json,
        config=config,
        out_dir=render_out,
        script=script,
    )
    print(f"Done. Outputs: {render_out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
