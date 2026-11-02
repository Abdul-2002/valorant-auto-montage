#!/bin/bash
set -euo pipefail
ROOT=/mnt/c/Users/aasid/OneDrive/Documents/valorant-montage-bot
cd "$ROOT"

# Ensure transport + title fixes are in the running containers
for c in valorant-montage-bot-api-1 valorant-montage-bot-worker-1; do
  docker cp src/youtube/upload.py "$c:/app/src/youtube/upload.py"
  docker cp src/youtube/job.py "$c:/app/src/youtube/job.py"
  docker cp src/youtube/listing.py "$c:/app/src/youtube/listing.py"
done
docker restart valorant-montage-bot-worker-1
sleep 8

# Channel check
curl -s http://127.0.0.1:8000/youtube/channels | tee /tmp/yt_channels.json
echo

python3 "$ROOT/scripts/_yt_upload_mood.py" | tee "$ROOT/data/yt_upload_live.log"
echo EXIT:$?
