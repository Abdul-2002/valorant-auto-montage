#!/bin/bash
set -euo pipefail
ROOT=/mnt/c/Users/aasid/OneDrive/Documents/valorant-montage-bot
cd "$ROOT"
docker compose up -d api worker
sleep 10
for c in valorant-montage-bot-api-1 valorant-montage-bot-worker-1; do
  docker cp src/youtube/upload.py "$c:/app/src/youtube/upload.py"
  docker cp src/youtube/job.py "$c:/app/src/youtube/job.py"
  docker cp src/youtube/listing.py "$c:/app/src/youtube/listing.py"
done
docker restart valorant-montage-bot-worker-1
sleep 6
docker exec -w /app valorant-montage-bot-api-1 python - <<'PY'
from src.youtube.settings import oauth_settings, _find_client_file
s = oauth_settings()
print("client_file", _find_client_file())
print("redirect", s.redirect_uri)
print("client_id_prefix", s.client_id[:28])
PY
echo CONNECT_URL=$(curl -s -o /dev/null -w '%{redirect_url}' http://127.0.0.1:8000/youtube/connect)
