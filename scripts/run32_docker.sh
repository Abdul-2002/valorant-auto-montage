#!/usr/bin/env bash
set -euo pipefail
cd /mnt/c/Users/aasid/OneDrive/Documents/valorant-montage-bot
mkdir -p artifacts/run32
docker compose -f docker-compose.run32.yaml build render
docker compose -f docker-compose.run32.yaml run --rm render
echo "RUN32_RENDER_DONE"
