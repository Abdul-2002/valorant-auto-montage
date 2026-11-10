"""Fine-tune Valorant kill-banner YOLO with Ultralytics.

Keeps class names aligned with models/auto_gaming_valorant.pt / training/data.yaml.
Does not print secrets. Requires ultralytics installed in the active environment.
"""

from __future__ import annotations

import argparse
from pathlib import Path


TRAINING_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TRAINING_ROOT.parent
DEFAULT_DATA = TRAINING_ROOT / "data.yaml"


def _default_weights() -> Path:
    candidates = (
        TRAINING_ROOT / "weights" / "auto_gaming_valorant.pt",
        REPO_ROOT / "models" / "auto_gaming_valorant.pt",
    )
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]
EXPECTED_NAMES = {
    0: "kill-1",
    1: "kill-2",
    2: "kill-3",
    3: "kill-4",
    4: "kill-5",
    5: "kill-6",
    6: "round-end",
    7: "round-start",
    8: "spectating",
    9: "spike-plant",
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fine-tune Valorant kill-banner YOLO")
    p.add_argument("--data", type=Path, default=DEFAULT_DATA, help="Ultralytics data.yaml")
    p.add_argument(
        "--weights",
        type=Path,
        default=_default_weights(),
        help="Base checkpoint (prefer current auto_gaming weights)",
    )
    p.add_argument("--epochs", type=int, default=50)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--device", type=str, default="0", help="CUDA index or 'cpu'")
    p.add_argument(
        "--project",
        type=Path,
        default=TRAINING_ROOT / "runs",
        help="Ultralytics project dir (gitignored via runs/)",
    )
    p.add_argument("--name", type=str, default="kill_banner_ft")
    return p.parse_args()


def _assert_names(names: dict[int, str]) -> None:
    normalized = {int(k): str(v) for k, v in names.items()}
    if normalized != EXPECTED_NAMES:
        raise SystemExit(
            "Class names/IDs do not match auto_gaming_valorant.pt taxonomy.\n"
            f"expected={EXPECTED_NAMES}\n"
            f"got={normalized}"
        )


def main() -> None:
    args = _parse_args()
    if not args.data.is_file():
        raise SystemExit(f"Missing data yaml: {args.data}")
    if not args.weights.is_file():
        raise SystemExit(f"Missing weights: {args.weights}")

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit("ultralytics is required: pip install ultralytics") from exc

    model = YOLO(str(args.weights))
    _assert_names(dict(model.names))

    model.train(
        data=str(args.data.resolve()),
        epochs=int(args.epochs),
        imgsz=int(args.imgsz),
        batch=int(args.batch),
        device=args.device,
        project=str(args.project.resolve()),
        name=str(args.name),
        exist_ok=True,
    )
    print(f"done project={args.project} name={args.name}", flush=True)


if __name__ == "__main__":
    main()
