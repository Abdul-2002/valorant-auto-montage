#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p outputs/run1
bash scripts/materialize_run1_videos.sh
docker compose -f docker-compose.run1.yaml run --rm render 2>&1 | tee outputs/run1/render.log
