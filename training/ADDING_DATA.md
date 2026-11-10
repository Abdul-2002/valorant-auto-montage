# Adding data to the dataset

Goal: extend labels for `models/auto_gaming_valorant.pt` **without changing class IDs/names**.

## Layout

```text
training/datasets/valorant_kill_banner/
  images/train/   *.jpg|*.png
  images/val/     *.jpg|*.png
  labels/train/   *.txt   # same stem as image
  labels/val/     *.txt
```

Each label line (YOLO normalized):

```text
class_id  x_center  y_center  width  height
```

Example (killfeed row top-right):

```text
0  0.86  0.08  0.18  0.04
```

## Class rules (do not renumber)

| ID | Name | Box what |
|---:|---|---|
| 0–5 | kill-1 … kill-6 | Each killfeed row / banner icon |
| 6 | round-end | Round-end banner only |
| 7 | round-start | Round-start banner only |
| 8 | spectating | Spectator / death-cam / SWITCH PLAYER UI |
| 9 | spike-plant | Plant notification banner |

Label **HUD overlays**, not enemy bodies or crosshair.

## Bulk raw dump (re-annotate yourself)

Keyless public zips (already includes Leaf48 ~9k frames):

```powershell
py -3.12 training/scripts/download_public_zips.py
```

Roboflow Universe packs (~18 datasets, tens of thousands more frames; mixed classes — OK):

```powershell
# Free key: https://app.roboflow.com → Account → API Keys
$env:ROBOFLOW_API_KEY = "rf_..."   # or ROBOFLOW_API_KEY= in .env; never commit
py -3.12 -m pip install roboflow
py -3.12 training/scripts/download_roboflow_raw.py
```

See `training/datasets/raw/SOURCES.md` for the full catalog. Class mismatch is fine — re-label yourself.

Workflow:

1. Download → `raw/<slug>/`
2. Open in Label Studio / CVAT / Roboflow / LabelImg
3. Re-label to the **10 classes** in `training/data.yaml` only
4. Export into `valorant_kill_banner/images/{train,val}` + `labels/{train,val}`

Do not train the production head on raw kota3/enemy labels as-is.

## Sources to merge (after re-label)

1. **Upstream Roboflow** packs listed in `raw/SOURCES.md`  
2. **Your VODs** — kill / buy / scoreboard / agent-select / death-cam stills (full-frame)  
3. **Hard negatives** — Gemini REJECT timestamps under `data/tasks/*/gemini_verified_kills/` (empty label or `spectating` box)

## Train / val split

- Keep ~80/20 by **image**, not by random crops of the same second.
- Prefer holding out whole matches/VODs for val so you don’t leak the same kill UI into both splits.

## Checklist before train

- [ ] Every `images/**/foo.jpg` has `labels/**/foo.txt` (empty file OK for negatives)
- [ ] No class IDs outside `0..9`
- [ ] No renamed classes (`kill` vs `kill-1` will break the bot)
- [ ] `training/data.yaml` `path` still points at this folder
