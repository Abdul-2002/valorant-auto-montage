#!/usr/bin/env bash
# Recompose + render run2: clip-driven bed, standard curation. Leaves run1 untouched.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p outputs/run2
bash scripts/materialize_run1_videos.sh
# Reuse detections + Gemini labels from run1 (no re-detect / quota burn).
cp -f outputs/run1/highlights.json outputs/run2/highlights.json
if [[ -f outputs/run1/play_labels.json ]]; then
  cp -f outputs/run1/play_labels.json outputs/run2/play_labels.json
fi
rm -f outputs/run2/song/music_edit.wav outputs/run2/song/music_contiguous.wav
docker compose -f docker-compose.run2.yaml run --rm --name montage-run2-rerender --entrypoint python render \
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
  --out /app/outputs/run2 \
  --config /app/config/run2.docker.yaml \
  --highlights /app/outputs/run2/highlights.json \
  2>&1 | tee outputs/run2/render.log
