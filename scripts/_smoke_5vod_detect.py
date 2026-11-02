"""Smoke: 5 VODs + Mood → create-from-paths → wait detect → recommendations."""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8000"
VIDEOS = Path("/videos")
SONGS = Path("/songs")


def get(path: str):
    with urllib.request.urlopen(API + path, timeout=120) as r:
        return json.load(r)


def post(path: str, body: dict):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def main() -> int:
    vids = sorted(
        [p for p in VIDEOS.glob("*.mp4") if p.is_file()],
        key=lambda p: p.stat().st_size,
    )
    # Skip tiny/no-kill outliers; take five mid clips (~310–400MB).
    picks = [p for p in vids if 280_000_000 <= p.stat().st_size <= 420_000_000][:5]
    if len(picks) < 4:
        picks = vids[1:6]  # skip smallest
    song = next(p for p in SONGS.glob("*.mp3") if "HandClap" not in p.name and "Mood" in p.name)
    print("videos", [p.name for p in picks])
    print("song", song.name)

    created = post(
        "/montage/create-from-paths",
        {"videos": [str(p) for p in picks], "music": str(song)},
    )
    tid = created["task_id"]
    print("task", tid)

    deadline = time.time() + 2400  # 40 min for 5 VODs on CPU YOLO
    last = None
    while time.time() < deadline:
        last = get(f"/montage/{tid}/status")
        print(
            "status",
            last.get("state"),
            last.get("phase"),
            last.get("progress"),
            flush=True,
        )
        if last.get("state") in {"SUCCESS", "FAILURE", "REVOKED"}:
            break
        time.sleep(10)

    hl = json.loads(Path(f"/data/tasks/{tid}/highlights.json").read_text(encoding="utf-8"))
    n = len(hl.get("highlights") or [])
    print("highlights", n)
    report = {
        "task_id": tid,
        "status": last,
        "num_highlights": n,
        "videos": [p.name for p in picks],
        "song": song.name,
    }
    if last and last.get("state") == "SUCCESS" and n > 0:
        rec = get(f"/montage/{tid}/recommendations?density=standard")
        ids = rec.get("recommended_ids") or [p["id"] for p in rec.get("plays") or []]
        report["plays"] = len(rec.get("plays") or [])
        report["recommended_ids"] = len(ids)
        print("plays", report["plays"], "recommended", report["recommended_ids"])
        report["ok"] = bool(ids)
    else:
        report["ok"] = False

    Path("/data/smoke_5vod_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("REPORT", json.dumps(report, indent=2))
    print("SMOKE_OK" if report["ok"] else "SMOKE_FAIL")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
