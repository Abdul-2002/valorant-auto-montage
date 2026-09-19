from __future__ import annotations

import os
from pathlib import Path

from src.config import AppConfig, load_config


def get_storage_dir() -> Path:
    return Path(os.environ.get("STORAGE_DIR", "data")).resolve()


def get_config() -> AppConfig:
    cfg_path = os.environ.get("MONTAGE_CONFIG_PATH", "config/default.yaml")
    return load_config(cfg_path)
