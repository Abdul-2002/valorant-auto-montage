import json
import urllib.request

url = "http://127.0.0.1:8000/montage/408734f8-27e8-4e3f-ad3b-3dfdec614b64/recommendations?density=standard"
with urllib.request.urlopen(url, timeout=30) as r:
    d = json.load(r)
print("plays", len(d.get("plays") or []), "ids", len(d.get("recommended_ids") or []))
print("SMOKE_REC_OK" if d.get("plays") else "SMOKE_REC_FAIL")
