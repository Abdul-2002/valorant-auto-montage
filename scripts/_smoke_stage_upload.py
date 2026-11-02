import json
import urllib.request
from pathlib import Path

base = "http://127.0.0.1:8000"


def post(path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def put_bytes(path: str, payload: bytes, filename: str):
    req = urllib.request.Request(
        f"{base}{path}?filename={urllib.parse.quote(filename)}",
        data=payload,
        headers={"Content-Type": "application/octet-stream"},
        method="PUT",
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)


import urllib.parse

sess = post("/montage/stage/session", {})
sid = sess["session_id"]
print("session", sid)
print(put_bytes(f"/montage/stage/{sid}/video_0", b"fake-video-bytes", "clip.mp4"))
print(put_bytes(f"/montage/stage/{sid}/music", b"fake-music-bytes", "song.mp3"))
created = post("/montage/create-from-stage", {"session_id": sid, "num_videos": 1})
print("task", created["task_id"])
meta = json.loads(Path(f"/data/tasks/{created['task_id']}/meta.json").read_text())
assert "/pending/" not in meta["videos"][0]
print("ok", meta["videos"][0])
