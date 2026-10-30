#!/usr/bin/env bash
set -euo pipefail
cd /mnt/c/Users/aasid/OneDrive/Documents/valorant-montage-bot
mkdir -p artifacts/run36
docker compose -f docker-compose.run36.yaml run --rm render
echo "RUN36_RENDER_DONE"
