# YOLO training (Valorant kill banner)

This folder is the fine-tune workspace for the **active** detector weights used by `auto_gaming_yolo`.

## Current production weight

| | |
|---|---|
| Path | `models/auto_gaming_valorant.pt` |
| Config | `config/default.yaml` → `detection.auto_gaming_yolo.model_path` |
| Detector | `src/detection/auto_gaming_yolo.py` |
| Inference crop | Full frame `[0,0,1,1]` (ROI starve kills) |

### Class taxonomy (must stay stable)

From the weight file / detector mapping:

| ID | YOLO name | Bot event |
|---:|---|---|
| 0–5 | `kill-1` … `kill-6` | `kill` |
| 6 | `round-end` | `round_boundary` |
| 7 | `round-start` | `round_boundary` |
| 8 | `spectating` | `game_state` |
| 9 | `spike-plant` | `objective` |

## How this model was trained (what we know vs unknown)

### Known (sourced)

1. **Upstream project**  
   [Noah-Grimaldi/auto-gaming-montage-maker](https://github.com/Noah-Grimaldi/auto-gaming-montage-maker) ships Valorant YOLO weights used for elimination/HUD detection.

2. **Dataset credited by that project**  
   Roboflow Universe — **Valorant kill banner** by Suman Kumar (~1.4k images):  
   https://universe.roboflow.com/suman-kumar-dx18l/valorant-kill-banner-woebs  

   Published classes match this weight pack:  
   `kill-1`…`kill-6`, `round-end`, `round-start`, `spectating`, `spike-plant`.

3. **This repo’s usage**  
   Weights are treated as a **full-frame** HUD detector. Kill emission uses rising-edge + cross-class dedupe because `kill-1`/`kill-2` can double-fire the same frag.

### Unknown (do not invent)

- Exact Ultralytics / YOLO version used by AGMM for the published `.pt`
- Epochs, batch size, image size, augmentations, optimizer schedule
- Train/val split and any private extra images beyond the Roboflow set

If you retrain here, record those hyperparameters in a dated note under `training/runs/` (gitignored) or append a short “Retrain log” section below.

## Other weights in `models/` (not active)

| File | Notes |
|---|---|
| `best_kill_only.pt` | Single class `kill` — incompatible with 10-class mapping |
| `valorant_killfeed_yolo11n.pt` | 13-class pack; `valorant_yolo` detector disabled |

## Fine-tune workflow

1. Populate data — see [ADDING_DATA.md](ADDING_DATA.md).
2. Confirm `training/data.yaml` class list unchanged.
3. Train from current weights (recommended) or a YOLO11n backbone:

```bash
python training/scripts/train_yolo.py --weights models/auto_gaming_valorant.pt
```

4. Validate with a held-out VOD / `gemini_verified_kills` REJECT set.
5. Copy best.pt → `models/auto_gaming_valorant.pt` (or new path + config update).
6. Smoke: run montage detect on a known clip; compare kill counts vs Gemini ACCEPT set.

## Retrain log

| Date | Base weights | Data notes | imgsz / epochs / batch | Result |
|---|---|---|---|---|
| _(add rows when you train)_ | | | | |
