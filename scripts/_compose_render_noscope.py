"""Compose+render without scoped CV / video probe / live Gemini labels (OneDrive hang workaround)."""
from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

DETECT_ID = "1f942c2f-8d2b-4639-aaa2-7ae47d60f476"
TDIR = Path(f"/data/tasks/{DETECT_ID}")
OUT = Path("/data/mood_render_report.json")
API = "http://127.0.0.1:8000"


def kill_dupes() -> None:
    me = os.getpid()
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        pid = int(d.name)
        if pid == me:
            continue
        try:
            cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
        except Exception:
            continue
        if any(x in cmd for x in ("_run_mood_render", "_finish_mood_from_task", "_kill_dup_and_compose")):
            print("kill", pid, flush=True)
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass


def http_get(path: str, timeout: int = 120):
    import urllib.request

    with urllib.request.urlopen(API + path, timeout=timeout) as r:
        return json.load(r)


def http_post(path: str, body: dict, timeout: int = 120):
    import urllib.request

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        API + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def wait_task(task_id: str, deadline_sec: float) -> dict:
    deadline = time.time() + deadline_sec
    last: dict = {}
    while time.time() < deadline:
        last = http_get(f"/montage/{task_id}/status")
        print("status", last.get("state"), last.get("phase"), last.get("progress"), flush=True)
        if last.get("state") in {"SUCCESS", "FAILURE", "REVOKED"}:
            return last
        time.sleep(8)
    return last


def main() -> int:
    kill_dupes()
    time.sleep(1)

    from src.ai.director import generate_montage_script
    from src.ai.enrichment import enrich_events
    from src.ai.engine.kill_grouping import build_play_flows
    from src.ai.engine.recommend import play_id, recommendations_payload
    from src.ai.schema import MontageScript
    from src.config.loader import load_config
    from src.pipeline.music_edit import prepare_edited_track
    from src.pipeline.types import DetectedEvent
    from src.worker.tasks import render_montage_task

    # Monkeypatch enrich_events defaults used by director
    import src.ai.director as director_mod

    _orig = director_mod.enrich_events

    def _fast_enrich(*, highlights, video_paths, detect_scope=True, probe_videos=True):
        return _orig(
            highlights=highlights,
            video_paths=video_paths,
            detect_scope=False,
            probe_videos=False,
        )

    director_mod.enrich_events = _fast_enrich

    # Skip live Gemini labeling inside director
    def _no_labels(plays, **kwargs):
        return plays

    director_mod.label_play_groups = _no_labels

    meta = json.loads((TDIR / "meta.json").read_text(encoding="utf-8"))
    videos = [Path(p) for p in meta["videos"]]
    music = Path(meta["music"])
    highlights = json.loads((TDIR / "highlights.json").read_text(encoding="utf-8"))["highlights"]
    events = [DetectedEvent.model_validate(x) for x in highlights]

    enriched, _ = enrich_events(
        highlights=events, video_paths=videos, detect_scope=False, probe_videos=False
    )
    plays = build_play_flows(enriched)
    rec = recommendations_payload(plays, density="standard")
    # Prefer all multi-kill flows + recommended singles so flow fix is visible in output
    multi_ids = [play_id(p) for p in plays if len(p.events) >= 2]
    rec_ids = list(rec.get("recommended_ids") or [])
    selected = list(dict.fromkeys(multi_ids + rec_ids))
    if not selected:
        selected = [play_id(p) for p in plays]
    print(
        "plays",
        len(plays),
        "multi",
        len(multi_ids),
        "selected",
        len(selected),
        flush=True,
    )
    (TDIR / "selection.json").write_text(
        json.dumps({"play_ids": selected, "density": "standard"}, indent=2), encoding="utf-8"
    )

    cfg_path = Path("/app/config/default.yaml")
    if not cfg_path.is_file():
        cfg_path = Path("config/default.yaml")
    config = load_config(cfg_path)
    print("prepare_edited_track…", flush=True)
    _, beat_map = prepare_edited_track(
        music,
        cache_dir=TDIR / "song",
        needed_sec=float(config.output.target_duration_sec),
        splice=False,
    )
    print("generate_montage_script…", flush=True)
    script, _ = generate_montage_script(
        highlights=highlights,
        video_paths=videos,
        config=config,
        beat_map=beat_map,
        brief=None,
        persist_path=TDIR / "montage_script.json",
        selected_play_ids=selected,
    )
    clips = script.clips
    multi_clips = []
    for c in clips:
        kills = list(c.kill_timestamps_sec or [])
        if not kills and c.kill_timestamp_sec is not None:
            kills = [c.kill_timestamp_sec]
        if len(kills) >= 2:
            multi_clips.append(
                {
                    "video_index": c.video_index,
                    "kill_count": len(kills),
                    "kills": kills,
                    "start_sec": c.start_sec,
                    "end_sec": c.end_sec,
                    "span_sec": float(c.end_sec) - float(c.start_sec),
                }
            )
    print("script_clips", len(clips), "multi_kill_clips", multi_clips, flush=True)

    render_task = render_montage_task.delay({"detect_task_id": DETECT_ID})
    render_id = render_task.id
    print("render_task", render_id, flush=True)
    rend = wait_task(render_id, 3600)

    out16 = TDIR / "outputs" / "montage_16x9.mp4"
    out916 = TDIR / "outputs" / "montage_9x16.mp4"
    report = {
        "ok": bool(rend.get("state") == "SUCCESS" and out16.is_file()),
        "detect_id": DETECT_ID,
        "render_id": render_id,
        "render_status": rend,
        "song": meta.get("music"),
        "videos": [Path(p).name for p in videos],
        "num_highlights": len(highlights),
        "num_plays": len(plays),
        "num_selected": len(selected),
        "multi_kill_plays": len(multi_ids),
        "multi_kill_play_ids": multi_ids,
        "script_clips": len(clips),
        "multi_kill_clips_in_script": multi_clips,
        "output_16x9": str(out16) if out16.is_file() else None,
        "output_16x9_bytes": out16.stat().st_size if out16.is_file() else 0,
        "output_9x16": str(out916) if out916.is_file() else None,
        "flow_fix_validated": len(multi_clips) > 0,
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print("RENDER_OK" if report["ok"] else "RENDER_FAIL", flush=True)
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
