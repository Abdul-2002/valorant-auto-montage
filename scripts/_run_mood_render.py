"""Full pipeline: 5 VODs + Mood → detect → recommend → compose → render; report multi-kill clips."""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8000"
OUT = Path("/data/mood_render_report.json")


def get(path: str, timeout: int = 120):
    with urllib.request.urlopen(API + path, timeout=timeout) as r:
        return json.load(r)


def post(path: str, body: dict | None = None, timeout: int = 600):
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
    last = None
    while time.time() < deadline:
        last = get(f"/montage/{task_id}/status")
        print(
            "status",
            last.get("state"),
            last.get("phase"),
            last.get("progress"),
            flush=True,
        )
        if last.get("state") in {"SUCCESS", "FAILURE", "REVOKED"}:
            return last
        time.sleep(8)
    return last or {}


def main() -> int:
    vids = sorted(Path("/videos").glob("*.mp4"), key=lambda p: p.stat().st_size)
    picks = [p for p in vids if 300_000_000 <= p.stat().st_size <= 420_000_000][:5]
    song = Path("/songs/24kGoldn - Mood (Official Video) ft. iann dior.mp3")
    if not song.is_file():
        song = next(p for p in Path("/songs").glob("*.mp3") if "Mood" in p.name)
    print("videos", [p.name for p in picks])
    print("song", song.name, song.stat().st_size)

    created = post(
        "/montage/create-from-paths",
        {"videos": [str(p) for p in picks], "music": str(song)},
    )
    detect_id = created["task_id"]
    print("detect_task", detect_id)

    det = wait_task(detect_id, 2400)
    hl = json.loads(Path(f"/data/tasks/{detect_id}/highlights.json").read_text(encoding="utf-8"))
    highlights = hl.get("highlights") or []
    print("highlights", len(highlights), "detect_state", det.get("state"))
    if det.get("state") != "SUCCESS" or not highlights:
        OUT.write_text(
            json.dumps(
                {"ok": False, "stage": "detect", "detect_id": detect_id, "status": det, "highlights": len(highlights)},
                indent=2,
            ),
            encoding="utf-8",
        )
        print("FAIL_DETECT")
        return 2

    rec = get(f"/montage/{detect_id}/recommendations?density=standard")
    ids = rec.get("recommended_ids") or [p["id"] for p in rec.get("plays") or [] if p.get("recommended")]
    if not ids:
        ids = [p["id"] for p in rec.get("plays") or []]
    print("plays", len(rec.get("plays") or []), "recommended", len(ids))
    multi_plays = [p for p in rec.get("plays") or [] if int(p.get("kill_count") or 0) >= 2]
    print("multi_kill_plays", len(multi_plays), [(p["kill_count"], p["id"][:40]) for p in multi_plays[:8]])

    post(
        f"/montage/{detect_id}/recommendations/confirm",
        {"play_ids": ids, "density": "standard"},
    )
    print("compose…", flush=True)
    composed = post(f"/montage/{detect_id}/compose", {}, timeout=900)
    print("compose", composed)

    script = get(f"/montage/{detect_id}/script")
    clips = script.get("script", {}).get("clips") or []
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
                    "enabled": c.get("enabled", True),
                }
            )
    print("script_clips", len(clips), "multi_kill_clips", len(multi_clips))

    # Trigger render via confirm highlights path using script endpoint save+render if available
    # Prefer POST /script which queues render.
    render_resp = post(
        f"/montage/{detect_id}/script",
        {"script": script["script"]},
        timeout=120,
    )
    render_id = render_resp.get("render_task_id") or render_resp.get("task_id")
    print("render_task", render_id, flush=True)
    rend = wait_task(str(render_id), 3600) if render_id else {}
    print("render_final", rend)

    out16 = Path(f"/data/tasks/{detect_id}/outputs/montage_16x9.mp4")
    out916 = Path(f"/data/tasks/{detect_id}/outputs/montage_9x16.mp4")
    report = {
        "ok": bool(rend.get("state") == "SUCCESS" and out16.is_file()),
        "detect_id": detect_id,
        "render_id": render_id,
        "detect_status": det,
        "render_status": rend,
        "song": song.name,
        "videos": [p.name for p in picks],
        "num_highlights": len(highlights),
        "num_plays": len(rec.get("plays") or []),
        "num_recommended": len(ids),
        "multi_kill_plays": len(multi_plays),
        "multi_kill_play_details": [
            {"kill_count": p["kill_count"], "id": p["id"], "recommended": p.get("recommended")}
            for p in multi_plays
        ],
        "script_clips": len(clips),
        "multi_kill_clips_in_script": multi_clips,
        "output_16x9": str(out16) if out16.is_file() else None,
        "output_16x9_bytes": out16.stat().st_size if out16.is_file() else 0,
        "output_9x16": str(out916) if out916.is_file() else None,
        "flow_fix_validated": len(multi_clips) > 0 or len(multi_plays) > 0,
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("REPORT", json.dumps(report, indent=2))
    print("RENDER_OK" if report["ok"] else "RENDER_FAIL")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
