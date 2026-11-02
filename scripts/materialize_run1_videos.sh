#!/usr/bin/env bash
# Copy the 10 run1 VODs into videos/ as real files (no D: symlink dependency).
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
for f in "${VIDEOS[@]}"; do
  dest="videos/$f"
  src="$SRC/$f"
  if [[ -f "$dest" && ! -L "$dest" && $(stat -c%s "$dest" 2>/dev/null || echo 0) -gt 1000000 ]]; then
    echo "ok (real): $f"
    continue
  fi
  if [[ ! -f "$src" ]]; then
    echo "MISSING source: $src" >&2
    exit 1
  fi
  rm -f "$dest"
  echo "copying $f ..."
  cp -f "$src" "$dest"
  echo "copied: $f ($(stat -c%s "$dest") bytes)"
done
echo "MATERIALIZE_OK"
