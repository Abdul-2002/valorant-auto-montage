"""Fast smoke: 2 mid VODs + Mood → detect SUCCESS → recommendations."""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8000"


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
    vids = sorted(Path("/videos").glob("*.mp4"), key=lambda p: p.stat().st_size)
    picks = [p for p in vids if 300_000_000 < p.stat().st_size < 390_000_000][:2]
    song = next(p for p in Path("/songs").glob("*.mp3") if "Mood" in p.name)
    print("picks", [p.name for p in picks], "song", song.name)
    tid = post(
        "/montage/create-from-paths",
        {"videos": [str(p) for p in picks], "music": str(song)},
    )["task_id"]
    print("task", tid)
    deadline = time.time() + 900
    last = None
    while time.time() < deadline:
        last = get(f"/montage/{tid}/status")
        print(last.get("state"), last.get("phase"), last.get("progress"), flush=True)
        if last.get("state") in {"SUCCESS", "FAILURE", "REVOKED"}:
            break
        time.sleep(5)
    n = len(json.loads(Path(f"/data/tasks/{tid}/highlights.json").read_text()).get("highlights") or [])
    print("highlights", n, "final", last)
    if not (last and last.get("state") == "SUCCESS" and n > 0):
        Path("/data/smoke_2vod_report.json").write_text(
            json.dumps({"ok": False, "task_id": tid, "status": last, "highlights": n}, indent=2)
        )
        print("SMOKE_FAIL")
        return 2
    rec = get(f"/montage/{tid}/recommendations?density=standard")
    ids = rec.get("recommended_ids") or [p["id"] for p in rec.get("plays") or []]
    report = {
        "ok": bool(ids),
        "task_id": tid,
        "highlights": n,
        "plays": len(rec.get("plays") or []),
        "recommended_ids": len(ids),
        "song": song.name,
        "videos": [p.name for p in picks],
    }
    Path("/data/smoke_2vod_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("REPORT", json.dumps(report, indent=2))
    print("SMOKE_OK" if report["ok"] else "SMOKE_FAIL")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
