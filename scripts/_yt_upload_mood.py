"""Queue + poll YouTube upload for Mood montage."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

API = "http://127.0.0.1:8000"
BODY = {
    "task_id": "1f942c2f-8d2b-4639-aaa2-7ae47d60f476",
    "channel_id": "UCd00JFTw3CZZNYpXmr2acag",
    "title": "24kGoldn - Mood | Valorant Montage",
    "description": "",
    "tags": ["valorant", "montage", "valorant montage", "24kGoldn", "Mood", "gaming"],
    "privacy_status": "public",
    "format": "16:9",
    "category_id": "20",
}


def post(path: str, body: dict, timeout: int = 120):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        API + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def get(path: str, timeout: int = 60):
    with urllib.request.urlopen(API + path, timeout=timeout) as r:
        return json.load(r)


def main() -> int:
    try:
        queued = post("/youtube/uploads", BODY)
    except urllib.error.HTTPError as exc:
        print("HTTP", exc.code, exc.read().decode(), flush=True)
        return 2
    upload_id = queued["upload_id"]
    print("queued", queued, flush=True)
    deadline = time.time() + 1800
    last: dict = {}
    while time.time() < deadline:
        last = get(f"/youtube/uploads/{upload_id}")
        print(
            "status",
            last.get("status"),
            last.get("title"),
            last.get("youtube_video_id"),
            last.get("error"),
            flush=True,
        )
        if last.get("status") in {"uploaded", "failed", "channel_mismatch"}:
            print(json.dumps(last, indent=2), flush=True)
            vid = last.get("youtube_video_id")
            if vid:
                print(f"https://www.youtube.com/watch?v={vid}", flush=True)
                return 0
            return 2
        time.sleep(5)
    print("timeout", json.dumps(last, indent=2), flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
