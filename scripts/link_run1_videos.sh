#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="${VALORANT_VIDEOS_SRC:-/mnt/d/Videos/Valorant}"
mkdir -p videos
VIDEOS=(
  "Valorant 2026.10.24 - 18.04.52.27.DVR.mp4"
  "Valorant 2026.10.23 - 23.07.34.24.DVR.mp4"
  "Valorant 2026.10.23 - 22.55.57.23.DVR.mp4"
  "Valorant 2026.10.23 - 22.53.05.22.DVR.mp4"
  "Valorant 2026.10.23 - 22.23.24.21.DVR.mp4"
  "Valorant 2026.10.20 - 15.31.23.17.DVR.mp4"
  "Valorant 2026.10.20 - 15.28.49.16.DVR.mp4"
  "Valorant 2026.10.20 - 14.55.33.15.DVR.mp4"
  "Valorant 2026.10.20 - 14.54.48.14.DVR.mp4"
  "Valorant 2026.10.20 - 14.50.15.13.DVR.mp4"
)
missing=0
for f in "${VIDEOS[@]}"; do
  if [[ ! -f "$SRC/$f" ]]; then
    echo "MISSING: $SRC/$f"
    missing=1
    continue
  fi
  ln -sfn "$SRC/$f" "videos/$f"
  echo "linked: $f"
done
exit "$missing"
