#!/usr/bin/env bash
set -euo pipefail
cd /mnt/c/Users/aasid/OneDrive/Documents/valorant-montage-bot
mkdir -p artifacts/run33
docker compose -f docker-compose.run33.yaml build render
docker compose -f docker-compose.run33.yaml run --rm render
echo "RUN33_RENDER_DONE"
