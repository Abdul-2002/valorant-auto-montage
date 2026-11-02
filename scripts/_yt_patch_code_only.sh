#!/bin/bash
set -euo pipefail
ROOT=/mnt/c/Users/aasid/OneDrive/Documents/valorant-montage-bot
cd "$ROOT"
for c in valorant-montage-bot-api-1 valorant-montage-bot-worker-1; do
  docker cp src/youtube/upload.py "$c:/app/src/youtube/upload.py"
  docker cp src/youtube/job.py "$c:/app/src/youtube/job.py"
  docker cp src/youtube/listing.py "$c:/app/src/youtube/listing.py"
done
docker restart valorant-montage-bot-worker-1
sleep 6
docker exec -w /app valorant-montage-bot-api-1 python -c 'from src.youtube.settings import oauth_settings; print(oauth_settings().redirect_uri)'
echo patches_ok
