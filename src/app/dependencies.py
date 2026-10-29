from __future__ import annotations

import os
from pathlib import Path

from src.config.models import AppConfig


def get_storage_dir() -> Path:
    return Path(os.environ.get("STORAGE_DIR", "data")).resolve()


def get_config() -> AppConfig:
    from src.config import load_config

    cfg_path = os.environ.get("MONTAGE_CONFIG_PATH", "config/default.yaml")
    return load_config(cfg_path)
