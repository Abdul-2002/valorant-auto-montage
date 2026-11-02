#!/bin/bash
set -euo pipefail
ROOT=/mnt/c/Users/aasid/OneDrive/Documents/valorant-montage-bot
cd "$ROOT"
SECRET=$(ls client_secret*.json | head -1)
for c in valorant-montage-bot-api-1 valorant-montage-bot-worker-1; do
  docker cp "$SECRET" "$c:/app/"
  docker cp src/youtube/upload.py "$c:/app/src/youtube/upload.py"
  docker cp src/youtube/job.py "$c:/app/src/youtube/job.py"
  docker cp src/youtube/listing.py "$c:/app/src/youtube/listing.py"
done
docker restart valorant-montage-bot-api-1 valorant-montage-bot-worker-1
sleep 10
docker exec -w /app valorant-montage-bot-api-1 python -c 'from src.youtube.settings import oauth_settings; s=oauth_settings(); print(s.redirect_uri); print("oauth_ok", bool(s.client_id))'
curl -s -o /dev/null -w 'connect_redirect=%{redirect_url}\n' http://127.0.0.1:8000/youtube/connect
