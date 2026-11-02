# Lost SI Studio

Web UI in `frontend/` for upload → flow-scored recommend → timeline edit → review → render.

## Run (Docker — full pipeline)

```bash
# From repo root — starts redis + api + worker + frontend + flower
docker compose up -d --build
```

| Service   | URL |
|-----------|-----|
| Studio UI | http://localhost:3000 |
| API docs  | http://localhost:8000/docs |
| Flower    | http://localhost:5555 |

GPU (optional, NVIDIA required):

```bash
docker compose -f docker-compose.yaml -f docker-compose.gpu.yaml up -d --build
```

The frontend proxies `/montage` → `http://api:8000`. Detect/render run on the Celery **worker**.

## Run (local Vite only)

```bash
# Still need API on :8000 (e.g. docker compose up -d redis api worker)
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 (Vite proxies `/montage` to `127.0.0.1:8000`).

## Flow scoring

Backend: `src/ai/engine/flow_scoring.py`  
API: `GET /montage/{id}/recommendations`, `POST .../confirm`, `POST .../compose`

## AI Montage Maker

Upload screen primary CTA runs: upload → detect → recommend → compose → builds multi-track timeline
(video / music / text / FX) via `frontend/src/studio/runAiMontage.ts` + `editor/buildTimeline.ts`.

Media preview: `GET /montage/{id}/media/video/{index}`, `GET /montage/{id}/media/music`

## Editor

Pro-referenced layout (media | preview | inspector | timeline). Final encode remains MoviePy via
`POST /montage/{id}/script`.
