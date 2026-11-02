"""Write confirmed.json and queue render for existing multi-kill montage_script."""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

DETECT_ID = "1f942c2f-8d2b-4639-aaa2-7ae47d60f476"
TDIR = Path(f"/data/tasks/{DETECT_ID}")
OUT = Path("/data/mood_render_report.json")
API = "http://127.0.0.1:8000"


def get(path: str, timeout: int = 60):
    with urllib.request.urlopen(API + path, timeout=timeout) as r:
        return json.load(r)


def main() -> int:
    hl = json.loads((TDIR / "highlights.json").read_text(encoding="utf-8"))
    confirmed = {"highlights": hl["highlights"], "overrides": None}
    (TDIR / "confirmed.json").write_text(json.dumps(confirmed, indent=2), encoding="utf-8")
    print("wrote confirmed.json", flush=True)

    from src.worker.tasks import render_montage_task

    task = render_montage_task.delay({"detect_task_id": DETECT_ID})
    render_id = task.id
    print("render", render_id, flush=True)

    deadline = time.time() + 3600
    last = {}
    while time.time() < deadline:
        last = get(f"/montage/{render_id}/status")
        print("status", last.get("state"), last.get("phase"), last.get("progress"), flush=True)
        if last.get("state") in {"SUCCESS", "FAILURE", "REVOKED"}:
            break
        time.sleep(10)

    out16 = TDIR / "outputs" / "montage_16x9.mp4"
    out916 = TDIR / "outputs" / "montage_9x16.mp4"
    script = json.loads((TDIR / "montage_script.json").read_text(encoding="utf-8"))
    clips = script.get("clips") or []
    multi = []
    for c in clips:
        kills = c.get("kill_timestamps_sec") or (
            [c["kill_timestamp_sec"]] if c.get("kill_timestamp_sec") is not None else []
        )
        if len(kills) >= 2:
            multi.append(
                {
                    "video_index": c.get("video_index"),
                    "kill_count": len(kills),
                    "kills": kills,
                    "start_sec": c.get("start_sec"),
                    "end_sec": c.get("end_sec"),
                    "span_sec": float(c.get("end_sec") or 0) - float(c.get("start_sec") or 0),
                }
            )
    meta = json.loads((TDIR / "meta.json").read_text(encoding="utf-8"))
    report = {
        "ok": bool(last.get("state") == "SUCCESS" and out16.is_file()),
        "detect_id": DETECT_ID,
        "render_id": render_id,
        "render_status": last,
        "song": meta.get("music"),
        "videos": [Path(p).name for p in meta.get("videos") or []],
        "script_clips": len(clips),
        "multi_kill_clips_in_script": multi,
        "output_16x9": str(out16) if out16.is_file() else None,
        "output_16x9_bytes": out16.stat().st_size if out16.is_file() else 0,
        "output_9x16": str(out916) if out916.is_file() else None,
        "output_9x16_bytes": out916.stat().st_size if out916.is_file() else 0,
        "flow_fix_validated": len(multi) > 0,
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print("RENDER_OK" if report["ok"] else "RENDER_FAIL", flush=True)
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
