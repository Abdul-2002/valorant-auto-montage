# Lost SI Studio — Full Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` or `subagent-driven-development` only after the user says **implement**. Steps use checkbox (`- [ ]`) syntax for tracking. Valere: agent must **not** `git commit` / `git push` — leave commits to the human.

**Goal:** Ship a production Lost SI web studio in `valorant-montage-bot/frontend/` with upload → AI score/recommend → Pro-grade timeline editor → preview → confirm render, backed by an explicit **flow scoring** system in the Python montage pipeline.

**Architecture:** Keep FastAPI + Celery + MoviePy/ffmpeg as the AI/detect/final-encode backend. Rebuild `frontend/` into a multi-screen Vite + React studio that **references** `C:\Users\aasid\OneDrive\Documents\react-video-editor-pro-main` (layout, timeline, Remotion player, media panels, overlays) without relocating the product into that Next.js repo. AI compose produces a `MontageScript`; the editor maps it to timeline overlays for preview/edit; `POST /montage/{id}/script` triggers final render.

**Tech Stack:** Vite, React 18, TypeScript, React Router, Zustand, Tailwind, Remotion Player (`@remotion/player` + `remotion` — same family as Pro), FastAPI montage API, existing clip-driven composer + new `flow_score` module.

**Spec / Intent (locked in chat):**
- Pro = **reference only**; product lives in `@frontend/`.
- Scoring decides which clips make a better montage **flow** (not only kill impact).
- Full product screens: upload, selection/recommended, editor (proper), preview, render gate.
- Scope = **all of the above**, not a throwaway MVP-only cut.

**Reference root:** `C:\Users\aasid\OneDrive\Documents\react-video-editor-pro-main\app\reactvideoeditor\pro\`  
Key Pro surfaces to mirror: `components/core/editor.tsx`, `video-player`, `timeline-section`, overlay panels, local-media upload, Remotion `utils/remotion/*`.

## Global Constraints

- Tesr: no code until user says **implement**; then smallest vertical slices that still complete the full vision.
- Valere: no agent git commit/push; pin dependency versions; no secrets in repo; `.env.example` only.
- Final pixel encode remains MoviePy/ffmpeg in Docker (existing pipeline). Remotion is **preview + edit UX**, not the only encoder, unless a later explicit decision changes that.
- Do not overwrite `outputs/run1` baselines; new studio runs use task storage / `outputs/studio-*`.
- Gemini free-tier quotas: prefer label cache; scoring must work unlabeled.
- Karpathy: no drive-by refactors outside listed files.

## Review Focus

1. Empty / all-junk detections → recommend UI must fail clearly, not invent clips.
2. Script↔timeline round-trip → reorder/trim in UI must survive `POST /script` and match preview.
3. Preview vs final encode drift → document allowed deltas (effects not in Remotion preview).
4. Large multi-VOD uploads → progress, cancel, disk limits.
5. Music phase / clip-driven bed → editor timeline duration must match composed bed, not raw song length.

---

## Product screens (target IA)

| Route | Screen | Purpose |
|-------|--------|---------|
| `/` | Home / Projects | Recent tasks, new montage |
| `/upload` | Upload | Multi-VOD + song, config (duration mode, density, layout) |
| `/jobs/:id/detect` | Detect progress | Status polling |
| `/jobs/:id/select` | Recommended selector | Scored plays, AI picks + manual override |
| `/jobs/:id/compose` | Compose progress | Script generation |
| `/jobs/:id/edit` | Editor | Timeline + Remotion preview + overlays (Pro-like) |
| `/jobs/:id/review` | Review gate | Side-by-side checklist; Confirm render |
| `/jobs/:id/render` | Render progress + download | Final MP4 |
| `/logs` | Logs | Keep existing Docker logs view |

---

## File map (new / major)

### Backend
- Create: `src/ai/engine/flow_scoring.py` — per-play + sequence flow scores
- Create: `src/ai/engine/recommend.py` — recommended set + alternatives
- Modify: `src/ai/engine/kill_grouping.py` / `composer.py` — consume flow scores
- Modify: `src/app/routes/montage.py` — recommend + compose-preview endpoints
- Modify: `src/app/schemas/montage.py` — DTOs for scores / recommendations
- Create: `tests/test_flow_scoring.py`

### Frontend
- Replace thin Studio with app shell under `frontend/src/`:
  - `app/router.tsx`, `app/shell.tsx`
  - `screens/Home.tsx`, `Upload.tsx`, `Detect.tsx`, `Select.tsx`, `Compose.tsx`, `Edit.tsx`, `Review.tsx`, `Render.tsx`
  - `editor/` — timeline, player, overlays (adapted from Pro patterns)
  - `state/projectStore.ts` (Zustand)
  - `api/montage.ts` — extend existing client
- Modify: `frontend/package.json` — Remotion player, router, zustand, tailwind
- Modify: `frontend/server/index.js` — proxy `/montage` to FastAPI; media static for task inputs

---

### Task 1: Flow scoring engine (backend)

**Files:**
- Create: `src/ai/engine/flow_scoring.py`
- Create: `tests/test_flow_scoring.py`
- Modify: `src/ai/engine/kill_grouping.py` (attach scores on groups)
- Modify: `src/ai/engine/composer.py` (select using flow, not only `_group_value`)

**Score model (explicit):**
- Per play `impact` (existing label/kills/HS)
- Per play `watchability` (source window length sanity, not truncated VOD edge)
- Sequence `pacing` (avoid too many 1-kill punches in a row; alternate densities)
- Sequence `arc` (rising impact into finale; opener not the peak)
- Sequence `variety` (video_index / label diversity)
- Combined `flow_score` used for recommend + curation order

**Steps:**
- [ ] Write failing tests: junk ranked below multi; sequence with only singles scores lower than mixed multi+HS; finale preference preserved
- [ ] Implement pure functions `score_play`, `score_sequence`, `rank_for_flow`
- [ ] Wire into `curate_plays` / `select_kill_groups` behind config flag `ai_director.use_flow_scoring: true`
- [ ] Unit smoke via docker `scripts/_run_unit_smoke.py` or pytest in image

---

### Task 2: Recommend + compose API surface

**Files:**
- Modify: `src/app/schemas/montage.py`
- Modify: `src/app/routes/montage.py`
- Modify: `src/worker/tasks.py` (optional detect-side label+score artifact)
- Modify: `frontend/src/api/montage.ts` + `types.ts`

**Endpoints:**
- `GET /montage/{id}/recommendations` → scored plays, `recommended_ids`, reject reasons
- `POST /montage/{id}/recommendations/confirm` → locked selection set
- `POST /montage/{id}/compose` → build `montage_script.json` without full render (preview path)
- Keep existing `POST /script` for edit→render

**Steps:**
- [ ] Schemas + route stubs with tests / OpenAPI check
- [ ] Persist `recommendations.json` + `selection.json` under task dir
- [ ] Compose-only task or sync compose using existing `generate_montage_script`
- [ ] Frontend API client methods

---

### Task 3: Frontend foundation (shell, routing, design tokens)

**Files:**
- Create: `frontend/src/app/*`, Tailwind config, design tokens inspired by Pro dark editor chrome
- Modify: `frontend/src/ui/App.tsx` → thin re-export or delete in favor of router
- Modify: `frontend/package.json`, `vite.config.ts`

**Steps:**
- [ ] Add React Router, Zustand, Tailwind; pin exact versions
- [ ] App shell with nav: Projects / New / Logs
- [ ] Empty screen stubs for every route in the IA table
- [ ] Proxy FastAPI + task media URLs through `frontend/server`

---

### Task 4: Upload + Detect screens

**Files:**
- Create: `frontend/src/screens/Upload.tsx`, `Detect.tsx`
- Modify: `frontend/server/index.js` (upload size limits, progress if needed)

**Steps:**
- [ ] Multi-file VOD + song dropzone (Pro local-media UX patterns)
- [ ] Options: layout, `duration_mode`, `curation_density`, flow scoring toggle
- [ ] Call `POST /montage/create`; poll status; navigate to Select when highlights ready
- [ ] Error / retry states

---

### Task 5: Recommended selector screen

**Files:**
- Create: `frontend/src/screens/Select.tsx`, `components/PlayCard.tsx`

**Steps:**
- [ ] Load recommendations; show score breakdown (impact / pacing contribution)
- [ ] Default-on recommended set; user toggles; “AI suggest” re-rank
- [ ] Clip scrub thumbnails (ffmpeg poster or browser video seek)
- [ ] Confirm → compose

---

### Task 6: Editor core (Pro-referenced timeline + Remotion preview)

**Files:**
- Create: `frontend/src/editor/**` adapted from Pro concepts (`editor.tsx`, `video-player`, `timeline-section`, overlay store)
- Create: Remotion composition that plays source VOD subclips per `MontageScript` slots
- Create: `frontend/src/screens/Edit.tsx`

**Editor capabilities (full studio set — all required):**
- Multi-track timeline (video clips, music bed, SFX/duck markers)
- Scrub, play/pause, zoom timeline
- Reorder clips, trim in/out, disable clip, split (optional if Remotion overlay model supports)
- Text overlays (title / engagement) editable
- Aspect 16:9 / 9:16 preview
- Undo/redo, autosave script draft to task API
- Keyboard shortcuts (J/K/L or space, delete)

**Steps:**
- [ ] Map `MontageScript` ↔ editor overlay model (document mapping table in `docs/`)
- [ ] Remotion Player preview from task media URLs
- [ ] Timeline CRUD updates Zustand + dirty flag
- [ ] Save draft `PUT/POST` script without render
- [ ] Visual parity pass against Pro chrome (panels, header, dark theme) — not a pixel fork

---

### Task 7: Review gate + Render

**Files:**
- Create: `frontend/src/screens/Review.tsx`, `Render.tsx`

**Steps:**
- [ ] Review: duration, clip count, labels, music bed, warnings (Gemini quota, demucs fallback)
- [ ] Explicit **Render** CTA → `POST /montage/{id}/script` with edited script
- [ ] Progress + download; keep Logs linked

---

### Task 8: Effects / AI feature surfacing in editor

**Files:**
- Editor side panels; backend script fields already on `ScriptClip`

**Steps:**
- [ ] Per-clip recipe / hit style / slowmo toggles bound to script fields the assembler already understands
- [ ] Show which effects are preview-approx vs final-only (ghost/SAM, jigsaw) with badges
- [ ] Music duck / kill markers visible on audio track

---

### Task 9: Integration hardening

**Steps:**
- [ ] E2E happy path: upload sample → recommend → edit trim → render
- [ ] Regression: clip-driven duration still follows plays; dense vs standard selectable in Upload
- [ ] Load test: 10 VODs as run2 inputs through studio API
- [ ] Docs: `docs/studio.md` operator guide; update root README

---

## Delivery order (still “all the things”)

1. Task 1–2 (scoring + API) — montage flow quality foundation  
2. Task 3–5 (shell + upload + select) — usable product without editor  
3. Task 6–7 (editor + review/render) — Pro-like editing + gate  
4. Task 8–9 (effects surfacing + harden) — feature completeness  

## Out of scope (explicit)

- Moving the product into the Next.js Pro repo as the deploy host  
- Replacing MoviePy final encode with Remotion Lambda in v1 of this plan  
- Training new YOLO weights  
- Fixing Pro’s upstream README merge conflict inside the reference repo (optional cleanup only if we vendor files)

## Success criteria

- User can go Upload → Select (scored) → Edit (preview) → Review → Render without CLI  
- Recommended set measurably prefers multi/ace/HS flow over random singles (unit + A/B vs run2)  
- Edited timeline changes appear in final MP4  
- `frontend/` is the only user-facing studio; Pro remains reference  

---

## Confirmation gate

Reply **yes** to approve this plan, or refine lines (especially Remotion-preview vs final-encode boundary).  
After **yes**, say **implement** (or **implement Task N**) to start code — tesr requires that trigger.
