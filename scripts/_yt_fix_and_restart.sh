#!/bin/bash
set -euo pipefail
cd /mnt/c/Users/aasid/OneDrive/Documents/valorant-montage-bot
SECRET=$(ls client_secret*.json | head -1)
echo "secret_file=$SECRET"
docker cp "$SECRET" valorant-montage-bot-api-1:/app/
docker cp "$SECRET" valorant-montage-bot-worker-1:/app/
docker cp src/youtube/listing.py valorant-montage-bot-api-1:/app/src/youtube/listing.py
docker cp src/youtube/listing.py valorant-montage-bot-worker-1:/app/src/youtube/listing.py
docker restart valorant-montage-bot-api-1 valorant-montage-bot-worker-1
sleep 12
docker exec valorant-montage-bot-worker-1 bash -c 'ls /app/client_secret*.json'
docker exec -w /app valorant-montage-bot-api-1 python -c 'from src.youtube.settings import oauth_settings; s=oauth_settings(); print("oauth_ok", bool(s.client_id))'
