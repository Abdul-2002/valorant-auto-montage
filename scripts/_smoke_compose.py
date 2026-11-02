import json
import urllib.request

API = "http://127.0.0.1:8000"
TID = "408734f8-27e8-4e3f-ad3b-3dfdec614b64"


def post(path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        API + path,
        data=data,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


rec = json.load(urllib.request.urlopen(API + f"/montage/{TID}/recommendations?density=standard", timeout=30))
ids = rec.get("recommended_ids") or [p["id"] for p in rec["plays"] if p.get("recommended")]
print("confirming", ids[:8])
print(post(f"/montage/{TID}/recommendations/confirm", {"play_ids": ids, "density": "standard"}))
print(post(f"/montage/{TID}/compose", {}))
script = json.load(urllib.request.urlopen(API + f"/montage/{TID}/script", timeout=30))
clips = script.get("script", {}).get("clips") or []
print("script_clips", len(clips))
print("COMPOSE_OK" if clips else "COMPOSE_FAIL")
