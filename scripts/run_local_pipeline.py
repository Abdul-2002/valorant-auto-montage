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
from src.pipeline.highlight_detector import detect_highlights
from src.pipeline.kill_assets import attach_ghost_cutouts
from src.pipeline.montage_assembler import render_montage
from src.pipeline.music_edit import prepare_edited_track
from src.pipeline.types import DetectedEvent


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Local end-to-end montage pipeline")
    p.add_argument(
        "--video",
        required=True,
        type=Path,
        nargs="+",
        help="One or more gameplay video paths (multi-VOD montages supported)",
    )
    p.add_argument("--music", required=True, type=Path, help="Music track path")
    p.add_argument("--out", type=Path, default=ROOT / "artifacts/local_pipeline_run", help="Output directory")
    p.add_argument("--config", type=Path, default=ROOT / "config/default.yaml")
    p.add_argument("--highlights", type=Path, default=None, help="Reuse an existing highlights.json and skip detection")
    args = p.parse_args()

    videos = [v.resolve() for v in args.video]
    music = args.music.resolve()
    out = args.out.resolve()
    for video in videos:
        if not video.is_file():
            print(f"Video not found: {video}", file=sys.stderr)
            return 1
    if not music.is_file():
        print(f"Music not found: {music}", file=sys.stderr)
        return 1

    out.mkdir(parents=True, exist_ok=True)
    cfg_path = args.config if args.config.is_file() else ROOT / args.config
    config = load_config(cfg_path)

    if args.highlights is not None:
        print(f"Phase: reuse highlights {args.highlights}...", flush=True)
        payload = json.loads(args.highlights.read_text(encoding="utf-8"))
        highlights = [DetectedEvent.model_validate(h) for h in payload.get("highlights", payload)]
        print(f"  -> {len(highlights)} events", flush=True)
    else:
        print(f"Phase: highlight detection ({len(videos)} video(s))...", flush=True)
        highlights = detect_highlights(video_paths=videos, config=config)
        print(f"  -> {len(highlights)} events", flush=True)

    hl_json = [h.model_dump(mode="json") for h in highlights]
    (out / "highlights.json").write_text(json.dumps({"highlights": hl_json}, indent=2), encoding="utf-8")
    (out / "confirmed.json").write_text(
        json.dumps({"highlights": hl_json, "overrides": {}}, indent=2),
        encoding="utf-8",
    )

    print("Phase: music edit + beat analysis...", flush=True)
    music_for_render, beat_map = prepare_edited_track(
        music, cache_dir=out / "song", needed_sec=float(config.output.target_duration_sec)
    )
    print(
        f"  -> tempo ~{getattr(beat_map, 'tempo_bpm', None)} bpm, track={music_for_render.name}, "
        f"downbeats={len(getattr(beat_map, 'downbeat_times', []) or [])}",
        flush=True,
    )

    brief = None
    try:
        events = [DetectedEvent.model_validate(x) for x in hl_json]
        enriched, _durations = enrich_events(highlights=events, video_paths=videos)
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
        video_paths=videos,
        config=config,
        beat_map=beat_map,
        brief=brief,
        persist_path=script_path,
    )
    print(f"  -> {len(script.clips)} clips", flush=True)

    print("Phase: ghost cut-outs...", flush=True)
    w, h = (int(x) for x in str(config.output.resolution).lower().split("x"))
    script = attach_ghost_cutouts(
        script,
        video_paths=videos,
        out_dir=out,
        resolution=(w, h),
        sam_model_path=ROOT / config.detection.sam_model_path,
    )
    script_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")

    render_out = out / "outputs"
    render_out.mkdir(parents=True, exist_ok=True)
    print("Phase: render (MoviePy + ffmpeg)...", flush=True)
    render_montage(
        video_paths=videos,
        music_path=music_for_render,
        highlights=hl_json,
        config=config,
        out_dir=render_out,
        script=script,
        beat_map=beat_map,
        song_title=music.stem,
    )
    print(f"Done. Outputs: {render_out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
