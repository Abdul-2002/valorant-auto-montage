import json
import time
import urllib.request
from pathlib import Path

base = "http://127.0.0.1:8000"


def get(path: str):
    with urllib.request.urlopen(base + path) as r:
        return json.load(r)


def post(path: str, body: dict):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)


media = get("/montage/media/mounted")
videos = sorted(media["videos"], key=lambda v: v["size_bytes"])
song = media["songs"][0]
pick = videos[0]
print("pick", pick["name"], pick["size_bytes"])
created = post("/montage/create-from-paths", {"videos": [pick["path"]], "music": song["path"]})
tid = created["task_id"]
print("task", tid)
time.sleep(1)
meta = json.loads(Path(f"/data/tasks/{tid}/meta.json").read_text(encoding="utf-8"))
print("meta0", meta["videos"][0])
assert "/pending/" not in meta["videos"][0], meta
assert Path(meta["videos"][0]).is_file(), meta["videos"][0]
st = get(f"/montage/{tid}/status")
print("status", st["state"], st.get("phase"), st.get("progress"))
print("ok")
