# Valorant Montage Bot (Lost SI)

FastAPI + Celery + Redis pipeline that turns Valorant VODs into beat-synced montages (16:9 and 9:16), with a Vite studio UI for upload, detect, select, edit, and render.

## Stack

- **API** — FastAPI (`src/app`)
- **Worker** — Celery detect + render (`src/worker`)
- **AI director** — play grouping, flow scoring, compose (`src/ai`)
- **Studio** — React/Vite frontend (`frontend/`)
- **Optional** — YouTube upload (`src/youtube`)

## Requirements

- Docker + Docker Compose
- NVIDIA GPU optional (NVENC / CUDA if available)
- Place YOLO / detector weights under `models/` (see config)

## Quick start

```bash
cp .env.example .env
# set GEMINI_API_KEY if you use Gemini features
# set YOUTUBE_OAUTH_* if you use YouTube upload

docker compose up -d --build
```

| Service | URL |
|--|--|
| Studio | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Flower | http://localhost:5555 |

Put source clips in `videos/` and songs in `songs/` (or upload via the studio). Outputs land under `data/tasks/<id>/outputs/`.

## YouTube OAuth (optional)

1. Create a **Web application** OAuth client in Google Cloud.
2. Authorized redirect URI: `http://127.0.0.1:8000/youtube/callback`
3. Either set `YOUTUBE_OAUTH_CLIENT_ID` / `YOUTUBE_OAUTH_CLIENT_SECRET` in `.env`, **or** place a `client_secret*.json` in the project root (gitignored).
4. Open http://127.0.0.1:8000/youtube/connect and approve access.

## Layout

```
src/           backend + AI + pipeline + YouTube
frontend/      Lost SI Studio
config/        default.yaml and presets
tests/         pytest suite
assets/        templates / static assets
videos/        local VOD inputs (gitignored media)
songs/         local music (gitignored media)
data/          runtime task storage (gitignored)
```

## Dev notes

- Never commit `.env`, `client_secret*.json`, media, or model weights.
- Config: `config/default.yaml` (override with `MONTAGE_CONFIG_PATH`).
- Tests: `pytest` from the repo root (or inside the API image).
