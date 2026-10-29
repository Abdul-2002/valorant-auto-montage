#!/usr/bin/env bash
set -euo pipefail
MUSIC="/mnt/c/Users/aasid/Music/Fire Again.mp3"
if [[ ! -f "$MUSIC" ]]; then
  echo "MISSING_MUSIC $MUSIC"
  exit 1
fi
echo "OK_MUSIC $MUSIC"
missing=0
while IFS= read -r f; do
  path="/mnt/d/Videos/Valorant/$f"
  if [[ -f "$path" ]]; then
    echo "OK $f"
  else
    echo "MISSING $f"
    missing=1
  fi
done <<'EOF'
Valorant 2026.10.24 - 18.04.52.27.DVR.mp4
Valorant 2026.10.23 - 23.07.34.24.DVR.mp4
Valorant 2026.10.23 - 22.55.57.23.DVR.mp4
Valorant 2026.10.23 - 22.53.05.22.DVR.mp4
Valorant 2026.10.23 - 22.23.24.21.DVR.mp4
Valorant 2026.10.20 - 15.31.23.17.DVR.mp4
Valorant 2026.10.20 - 15.28.49.16.DVR.mp4
Valorant 2026.10.20 - 14.55.33.15.DVR.mp4
Valorant 2026.10.20 - 14.54.48.14.DVR.mp4
Valorant 2026.10.20 - 14.50.15.13.DVR.mp4
EOF
exit "$missing"
