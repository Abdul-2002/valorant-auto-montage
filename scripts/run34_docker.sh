#!/usr/bin/env bash
set -euo pipefail
cd /mnt/c/Users/aasid/OneDrive/Documents/valorant-montage-bot
mkdir -p artifacts/run34
docker compose -f docker-compose.run34.yaml run --rm render
echo "RUN34_RENDER_DONE"
