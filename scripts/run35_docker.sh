#!/usr/bin/env bash
set -euo pipefail
cd /mnt/c/Users/aasid/OneDrive/Documents/valorant-montage-bot
mkdir -p artifacts/run35
docker compose -f docker-compose.run35.yaml build render
docker compose -f docker-compose.run35.yaml run --rm render
echo "RUN35_RENDER_DONE"
