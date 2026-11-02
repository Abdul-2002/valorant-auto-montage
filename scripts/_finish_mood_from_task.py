"""Wait for detect task 1f942c2f… then recommend → compose → render; report multi-kill flow."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8000"
DETECT_ID = "1f942c2f-8d2b-4639-aaa2-7ae47d60f476"
OUT = Path("/data/mood_render_report.json")
LOG = Path("/data/mood_finish.log")


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def get(path: str, timeout: int = 120):
    with urllib.request.urlopen(API + path, timeout=timeout) as r:
        return json.load(r)


def post(path: str, body: dict | None = None, timeout: int = 900):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        API + path,
        data=data,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def wait_task(task_id: str, deadline_sec: float) -> dict:
    deadline = time.time() + deadline_sec
    last: dict = {}
    while time.time() < deadline:
        last = get(f"/montage/{task_id}/status")
        log(f"status {task_id[:8]} {last.get('state')} {last.get('phase')} {last.get('progress')}")
        if last.get("state") in {"SUCCESS", "FAILURE", "REVOKED"}:
            return last
        time.sleep(10)
    return last


def main() -> int:
    LOG.write_text("", encoding="utf-8")
    log(f"waiting detect {DETECT_ID}")
    det = wait_task(DETECT_ID, 3600)
    hl_path = Path(f"/data/tasks/{DETECT_ID}/highlights.json")
    highlights = []
    if hl_path.is_file():
        highlights = json.loads(hl_path.read_text(encoding="utf-8")).get("highlights") or []
    log(f"detect_state={det.get('state')} highlights={len(highlights)}")
    if det.get("state") != "SUCCESS" or not highlights:
        OUT.write_text(json.dumps({"ok": False, "stage": "detect", "status": det}, indent=2), encoding="utf-8")
        return 2

    meta = json.loads(Path(f"/data/tasks/{DETECT_ID}/meta.json").read_text(encoding="utf-8"))
    log(f"song={meta.get('music')} videos={len(meta.get('videos') or [])}")

    rec = get(f"/montage/{DETECT_ID}/recommendations?density=standard")
    plays = rec.get("plays") or []
    ids = rec.get("recommended_ids") or [p["id"] for p in plays if p.get("recommended")]
    if not ids:
        ids = [p["id"] for p in plays]
    multi_plays = [p for p in plays if int(p.get("kill_count") or 0) >= 2]
    log(f"plays={len(plays)} recommended={len(ids)} multi_kill_plays={len(multi_plays)}")
    for p in multi_plays:
        log(f"  multi {p.get('kill_count')} kills id={p.get('id')}")

    post(f"/montage/{DETECT_ID}/recommendations/confirm", {"play_ids": ids, "density": "standard"})
    log("compose…")
    composed = post(f"/montage/{DETECT_ID}/compose", {})
    log(f"compose {composed}")

    script_resp = get(f"/montage/{DETECT_ID}/script")
    script = script_resp["script"]
    clips = script.get("clips") or []
    multi_clips = []
    for c in clips:
        kills = c.get("kill_timestamps_sec") or (
            [c["kill_timestamp_sec"]] if c.get("kill_timestamp_sec") is not None else []
        )
        if len(kills) >= 2:
            multi_clips.append(
                {
                    "video_index": c.get("video_index"),
                    "kill_count": len(kills),
                    "kills": kills,
                    "start_sec": c.get("start_sec"),
                    "end_sec": c.get("end_sec"),
                    "span_sec": float(c.get("end_sec") or 0) - float(c.get("start_sec") or 0),
                    "enabled": c.get("enabled", True),
                }
            )
    log(f"script_clips={len(clips)} multi_kill_clips={len(multi_clips)}")

    render_resp = post(f"/montage/{DETECT_ID}/script", {"script": script}, timeout=120)
    render_id = render_resp.get("render_task_id")
    log(f"render_task={render_id}")
    rend = wait_task(str(render_id), 3600) if render_id else {}

    out16 = Path(f"/data/tasks/{DETECT_ID}/outputs/montage_16x9.mp4")
    out916 = Path(f"/data/tasks/{DETECT_ID}/outputs/montage_9x16.mp4")
    report = {
        "ok": bool(rend.get("state") == "SUCCESS" and out16.is_file()),
        "detect_id": DETECT_ID,
        "render_id": render_id,
        "detect_status": det,
        "render_status": rend,
        "song": meta.get("music"),
        "videos": [Path(p).name for p in (meta.get("videos") or [])],
        "num_highlights": len(highlights),
        "num_plays": len(plays),
        "num_recommended": len(ids),
        "multi_kill_plays": len(multi_plays),
        "multi_kill_play_details": [
            {"kill_count": p["kill_count"], "id": p["id"], "recommended": p.get("recommended")}
            for p in multi_plays
        ],
        "script_clips": len(clips),
        "multi_kill_clips_in_script": multi_clips,
        "compose": composed,
        "output_16x9": str(out16) if out16.is_file() else None,
        "output_16x9_bytes": out16.stat().st_size if out16.is_file() else 0,
        "output_9x16": str(out916) if out916.is_file() else None,
        "flow_fix_validated": len(multi_clips) > 0,
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log("REPORT_WRITTEN")
    log("RENDER_OK" if report["ok"] else "RENDER_FAIL")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        log(f"FATAL {type(e).__name__}: {e}")
        raise
