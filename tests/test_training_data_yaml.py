"""Smoke checks for training/data.yaml taxonomy."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
DATA_YAML = REPO / "training" / "data.yaml"

EXPECTED = {
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


def test_training_data_yaml_has_stable_ten_classes() -> None:
    assert DATA_YAML.is_file()
    raw = yaml.safe_load(DATA_YAML.read_text(encoding="utf-8"))
    names = {int(k): str(v) for k, v in dict(raw["names"]).items()}
    assert names == EXPECTED
    assert raw["train"] == "images/train"
    assert raw["val"] == "images/val"


def test_training_dataset_dirs_exist() -> None:
    root = REPO / "training" / "datasets" / "valorant_kill_banner"
    for rel in (
        "images/train",
        "images/val",
        "labels/train",
        "labels/val",
    ):
        assert (root / rel).is_dir()
