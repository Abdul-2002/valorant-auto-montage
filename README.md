## Valorant Montage Bot

FastAPI + Celery (Redis) service that turns raw Valorant gameplay (4–5 minute videos, 1–10+ inputs) into beat-synced montage outputs (16:9 + 9:16).

### What it does

- **Detect highlights (hybrid)**: kill-feed (template matching) + audio percussive peaks (HPSS+RMS)
- **Review/edit highlights** via API before rendering
- **Assemble montage**: beat-synced cuts, velocity edits, zoom, shake, color grading, transitions, audio mixing
- **Extensible**: effects, transitions, detectors are plugins discovered at runtime (registry + decorators)

### Local run (dev)

This project is designed to run with:
- `ffmpeg` installed (NVENC optional but recommended)
- Redis (for Celery broker/backend)

You’ll typically run with Docker Compose (see `docker-compose.yaml`) once implemented.

### UIs

- API docs: `http://localhost:8000/docs`
- Celery Flower: `http://localhost:5555`
- Frontend UI (logs now, editor later): `http://localhost:3000`

Note: the frontend mounts the Docker socket read-only so it can read container logs.

### Templates

Kill-feed detection requires template PNGs in `assets/templates/`:
- `kill_skull.png`
- `headshot_skull.png`
- `death_skull.png`
- `assist_icon.png`

Capture them from your own Valorant footage at native resolution with transparency when possible.
