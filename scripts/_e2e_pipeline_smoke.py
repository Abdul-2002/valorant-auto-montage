"""E2E smoke: parallel stage upload (same path as studio) → detect → recommendations."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8000"
HOST_VIDEOS = Path("/mnt/c/Users/aasid/OneDrive/Documents/valorant-montage-bot/videos")
HOST_SONGS = Path("/mnt/c/Users/aasid/OneDrive/Documents/valorant-montage-bot/songs")
# Prefer container paths when running inside api; host paths when running on WSL.
CONTAINER_VIDEOS = Path("/videos")
CONTAINER_SONGS = Path("/songs")


def get(path: str):
    with urllib.request.urlopen(API + path, timeout=60) as r:
        return json.load(r)


def post(path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(API + path, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def put_file(url: str, path: Path) -> dict:
    size = path.stat().st_size
    print(f"  PUT {path.name} ({size} bytes) …", flush=True)
    t0 = time.time()
    with path.open("rb") as f:
        data = f.read()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/octet-stream", "Content-Length": str(len(data))},
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        out = json.load(r)
    dt = time.time() - t0
    mbps = (size / (1024 * 1024)) / dt if dt > 0 else 0
    print(f"  done {out.get('bytes_written')} bytes in {dt:.1f}s ({mbps:.1f} MiB/s)", flush=True)
    return out


def pick_media() -> tuple[Path, Path]:
    vroot = CONTAINER_VIDEOS if CONTAINER_VIDEOS.is_dir() else HOST_VIDEOS
    sroot = CONTAINER_SONGS if CONTAINER_SONGS.is_dir() else HOST_SONGS
    videos = sorted([p for p in vroot.glob("*.mp4") if p.is_file()], key=lambda p: p.stat().st_size)
    songs = sorted([p for p in sroot.glob("*.mp3") if p.is_file()], key=lambda p: p.stat().st_size)
    if not videos or not songs:
        raise SystemExit(f"missing media under {vroot} / {sroot}")
    # smallest VOD for smoke (still real gameplay)
    return videos[0], songs[0]


def main() -> int:
    report: dict = {"steps": []}

    # 1–2) Frontend shell (from host network; containers cannot reach published :3000 via 127.0.0.1)
    for label, url, check in (
        ("frontend_html", "http://host.docker.internal:3000/", lambda b: "Lost SI Studio" in b and "index-" in b),
        ("frontend_upload_route", "http://host.docker.internal:3000/upload", lambda b: "root" in b or "Lost SI" in b or len(b) > 50),
    ):
        ok = False
        err = None
        for candidate in (url, url.replace("host.docker.internal", "172.17.0.1"), "http://frontend:3000/" if "upload" not in label else "http://frontend:3000/upload"):
            try:
                with urllib.request.urlopen(candidate, timeout=10) as r:
                    body = r.read().decode("utf-8", errors="replace")
                    ok = check(body) if label == "frontend_html" else (r.status == 200)
                if ok:
                    break
            except Exception as e:
                err = str(e)
        report["steps"].append({"step": label, "ok": ok, "error": None if ok else err})
        print(label, ok if ok else f"FAIL {err}")
        if not ok and label == "frontend_html":
            # Non-fatal inside Docker — host browser check is authoritative.
            print("continuing without in-container frontend fetch")

    # 3) Stage session + parallel-style PUTs (studio upload path)
    video, song = pick_media()
    print("media", video.name, video.stat().st_size, "+", song.name)
    sess = post("/montage/stage/session", {})
    sid = sess["session_id"]
    report["session_id"] = sid
    print("session", sid)

    qv = urllib.parse.urlencode({"filename": video.name})
    qm = urllib.parse.urlencode({"filename": song.name})
    t_upload = time.time()
    put_file(f"{API}/montage/stage/{sid}/video_0?{qv}", video)
    put_file(f"{API}/montage/stage/{sid}/music?{qm}", song)
    upload_s = time.time() - t_upload
    report["upload_sec"] = round(upload_s, 2)
    report["upload_bytes"] = video.stat().st_size + song.stat().st_size

    created = post("/montage/create-from-stage", {"session_id": sid, "num_videos": 1})
    tid = created["task_id"]
    report["task_id"] = tid
    print("task", tid)

    meta = json.loads(Path(f"/data/tasks/{tid}/meta.json").read_text(encoding="utf-8"))
    pending_ok = "/pending/" not in meta["videos"][0]
    files_ok = Path(meta["videos"][0]).is_file() and Path(meta["music"]).is_file()
    report["steps"].append({"step": "create_meta", "ok": pending_ok and files_ok, "meta0": meta["videos"][0]})
    print("meta_ok", pending_ok, files_ok, meta["videos"][0])

    # 4) Poll detect (cap wait — YOLO on 150MB+ can be long)
    deadline = time.time() + 900  # 15 min
    last = None
    while time.time() < deadline:
        st = get(f"/montage/{tid}/status")
        last = st
        print("status", st.get("state"), st.get("phase"), st.get("progress"), flush=True)
        if st.get("state") in {"SUCCESS", "FAILURE", "REVOKED"}:
            break
        time.sleep(5)
    report["final_status"] = last
    detect_ok = bool(last and last.get("state") == "SUCCESS")
    report["steps"].append({"step": "detect", "ok": detect_ok, "status": last})

    hl_path = Path(f"/data/tasks/{tid}/highlights.json")
    highlights = []
    if hl_path.is_file():
        highlights = json.loads(hl_path.read_text(encoding="utf-8")).get("highlights") or []
    report["num_highlights"] = len(highlights)
    print("highlights", len(highlights))

    # 5) Recommendations / compose only if we have kills
    if detect_ok and highlights:
        try:
            rec = get(f"/montage/{tid}/recommendations?density=standard")
            ids = rec.get("recommended_ids") or [p["id"] for p in rec.get("plays") or []]
            report["steps"].append(
                {"step": "recommendations", "ok": bool(ids), "plays": len(rec.get("plays") or []), "ids": len(ids)}
            )
            print("recommendations", len(rec.get("plays") or []), "ids", len(ids))
            if ids:
                post(
                    f"/montage/{tid}/recommendations/confirm",
                    {"play_ids": ids[: min(12, len(ids))], "density": "standard"},
                )
                composed = post(f"/montage/{tid}/compose", {})
                report["steps"].append({"step": "compose", "ok": True, "result": composed})
                print("compose", composed)
                script = get(f"/montage/{tid}/script")
                report["steps"].append(
                    {"step": "script", "ok": bool(script.get("script")), "clips": len(script.get("script", {}).get("clips") or [])}
                )
                print("script clips", len(script.get("script", {}).get("clips") or []))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            report["steps"].append({"step": "post_detect", "ok": False, "error": body})
            print("post_detect FAIL", body)
    else:
        report["steps"].append(
            {
                "step": "recommendations",
                "ok": False,
                "skipped": True,
                "reason": "detect failed or 0 highlights",
            }
        )

    report["done"] = all(s.get("ok") for s in report["steps"] if not s.get("skipped"))
    out = Path("/tmp/e2e_smoke_report.json")
    # also write host-visible copy if /data mounted
    host_out = Path("/data/e2e_smoke_report.json")
    text = json.dumps(report, indent=2)
    out.write_text(text, encoding="utf-8")
    try:
        host_out.write_text(text, encoding="utf-8")
    except OSError:
        pass
    print("REPORT", text)
    print("PIPELINE_DONE" if report["done"] else "PIPELINE_NOT_DONE")
    return 0 if report["done"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
