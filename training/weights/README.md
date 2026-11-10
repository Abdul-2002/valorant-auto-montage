# Weights

Runtime weights live in repo-root `models/` (gitignored `*.pt`). Do **not** commit `.pt` files here.

| File | Role | Classes |
|---|---|---|
| `models/auto_gaming_valorant.pt` | **Active** kill detector (`auto_gaming_yolo`) | 10 HUD classes (see `../data.yaml`) |
| `models/best_kill_only.pt` | Unused alternate | 1× `kill` |
| `models/valorant_killfeed_yolo11n.pt` | Unused (`valorant_yolo` disabled) | 13 mixed HUD/body/utils |

After fine-tuning, copy the best checkpoint to:

```text
models/auto_gaming_valorant.pt
```

(or point `config/default.yaml` → `detection.auto_gaming_yolo.model_path` at the new file).

Verify class names match before swapping:

```bash
python -c "from ultralytics import YOLO; print(YOLO('models/auto_gaming_valorant.pt').names)"
```
