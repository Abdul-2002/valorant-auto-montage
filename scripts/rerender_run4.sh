#!/usr/bin/env bash
# Run4: flow-scoring fix + clip-driven bed. Leaves run1–run3 untouched.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p outputs/run4
bash scripts/materialize_run1_videos.sh
cp -f outputs/run1/highlights.json outputs/run4/highlights.json
if [[ -f outputs/run1/play_labels.json ]]; then
  cp -f outputs/run1/play_labels.json outputs/run4/play_labels.json
fi
rm -f outputs/run4/song/music_edit.wav outputs/run4/song/music_contiguous.wav
docker compose -f docker-compose.run4.yaml run --rm --name montage-run4-rerender --entrypoint python render \
  scripts/run_local_pipeline.py \
  --video \
  "/videos/Valorant 2026.10.24 - 18.04.52.27.DVR.mp4" \
  "/videos/Valorant 2026.10.23 - 23.07.34.24.DVR.mp4" \
  "/videos/Valorant 2026.10.23 - 22.55.57.23.DVR.mp4" \
  "/videos/Valorant 2026.10.23 - 22.53.05.22.DVR.mp4" \
  "/videos/Valorant 2026.10.23 - 22.23.24.21.DVR.mp4" \
  "/videos/Valorant 2026.10.20 - 15.31.23.17.DVR.mp4" \
  "/videos/Valorant 2026.10.20 - 15.28.49.16.DVR.mp4" \
  "/videos/Valorant 2026.10.20 - 14.55.33.15.DVR.mp4" \
  "/videos/Valorant 2026.10.20 - 14.54.48.14.DVR.mp4" \
  "/videos/Valorant 2026.10.20 - 14.50.15.13.DVR.mp4" \
  --music "/songs/HandClap - Fitz and the Tantrums.mp3" \
  --out /app/outputs/run4 \
  --config /app/config/run4.docker.yaml \
  --highlights /app/outputs/run4/highlights.json \
  2>&1 | tee outputs/run4/render.log
