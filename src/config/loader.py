from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import AppConfig


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)  # type: ignore[arg-type]
        else:
            out[k] = v
    return out


def load_config(default_path: str | Path, overrides: dict[str, Any] | None = None) -> AppConfig:
    """
    Load YAML config and validate with Pydantic.

    Args:
        default_path: Path to the default YAML config file.
        overrides: Optional dict merged over the default config.

    Returns:
        Validated AppConfig.
    """
    path = Path(default_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if overrides:
        raw = _deep_merge(raw, overrides)
    return AppConfig.model_validate(raw)
