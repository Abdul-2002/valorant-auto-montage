import json
from pathlib import Path

root = Path("/mnt/c/Users/aasid/OneDrive/Documents/valorant-montage-bot")
path = next(root.glob("client_secret*.json"))
raw = json.loads(path.read_text(encoding="utf-8"))
block = raw.get("installed") or raw.get("web") or {}
print("redirects", block.get("redirect_uris"))
print("has_secret", bool(block.get("client_secret")))
