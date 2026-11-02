"""Kill duplicate mood waiters; compose+render 1f942 with all multi-kill plays selected."""
from __future__ import annotations

import json
import os
import signal
import time
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8000"
DETECT_ID = "1f942c2f-8d2b-4639-aaa2-7ae47d60f476"
OUT = Path("/data/mood_render_report.json")


def get(path: str, timeout: int = 120):
    with urllib.request.urlopen(API + path, timeout=timeout) as r:
        return json.load(r)


def post(path: str, body: dict | None = None, timeout: int = 1800):
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
        print("status", last.get("state"), last.get("phase"), last.get("progress"), flush=True)
        if last.get("state") in {"SUCCESS", "FAILURE", "REVOKED"}:
            return last
        time.sleep(8)
    return last


def kill_other_scripts() -> None:
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
        if "_run_mood_render" in cmd or "_finish_mood_from_task" in cmd:
            print("killing", pid, cmd[:80], flush=True)
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception as e:
                print("kill_fail", e)


def main() -> int:
    kill_other_scripts()
    time.sleep(1)

    rec = get(f"/montage/{DETECT_ID}/recommendations?density=standard")
    plays = rec.get("plays") or []
    # Select ALL plays so multi-kill flows land in the script (not just the single recommended).
    ids = [p["id"] for p in plays]
    multi = [p for p in plays if int(p.get("kill_count") or 0) >= 2]
    print("plays", len(plays), "multi", len(multi), "selecting_all", flush=True)

    post(f"/montage/{DETECT_ID}/recommendations/confirm", {"play_ids": ids, "density": "standard"})
    print("compose starting…", flush=True)
    t0 = time.time()
    composed = post(f"/montage/{DETECT_ID}/compose", {})
    print("compose done", time.time() - t0, composed, flush=True)

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
                }
            )
    print("clips", len(clips), "multi_clips", multi_clips, flush=True)

    render_resp = post(f"/montage/{DETECT_ID}/script", {"script": script}, timeout=120)
    render_id = render_resp.get("render_task_id")
    print("render", render_id, flush=True)
    rend = wait_task(str(render_id), 3600) if render_id else {}

    out16 = Path(f"/data/tasks/{DETECT_ID}/outputs/montage_16x9.mp4")
    out916 = Path(f"/data/tasks/{DETECT_ID}/outputs/montage_9x16.mp4")
    meta = json.loads(Path(f"/data/tasks/{DETECT_ID}/meta.json").read_text(encoding="utf-8"))
    report = {
        "ok": bool(rend.get("state") == "SUCCESS" and out16.is_file()),
        "detect_id": DETECT_ID,
        "render_id": render_id,
        "render_status": rend,
        "song": meta.get("music"),
        "videos": [Path(p).name for p in (meta.get("videos") or [])],
        "num_plays": len(plays),
        "multi_kill_plays": len(multi),
        "multi_kill_play_details": [
            {"kill_count": p["kill_count"], "id": p["id"]} for p in multi
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
    print(json.dumps(report, indent=2), flush=True)
    print("RENDER_OK" if report["ok"] else "RENDER_FAIL", flush=True)
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
