#!/bin/bash
set -euo pipefail
ROOT=/mnt/c/Users/aasid/OneDrive/Documents/valorant-montage-bot
cd "$ROOT"
docker cp src/youtube/upload.py valorant-montage-bot-worker-1:/app/src/youtube/upload.py
docker cp src/youtube/job.py valorant-montage-bot-worker-1:/app/src/youtube/job.py
docker cp src/youtube/upload.py valorant-montage-bot-api-1:/app/src/youtube/upload.py
docker cp src/youtube/job.py valorant-montage-bot-api-1:/app/src/youtube/job.py
# Ensure OAuth client JSON still present after any restart
SECRET=$(ls client_secret*.json | head -1)
docker cp "$SECRET" valorant-montage-bot-worker-1:/app/
docker cp "$SECRET" valorant-montage-bot-api-1:/app/
docker restart valorant-montage-bot-worker-1
sleep 10
docker exec valorant-montage-bot-worker-1 grep -n '_CHUNK =\|_CHUNK_TRANSPORT\|_stage_local' /app/src/youtube/upload.py /app/src/youtube/job.py
python3 "$ROOT/scripts/_yt_upload_mood.py"
