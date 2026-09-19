from __future__ import annotations

from typing import Any


PRESETS: dict[str, dict[str, Any]] = {
    "aggressive": {
        "pacing": 0.9,
        "effect_intensity": 0.8,
        "slowmo_bias": 0.7,
        "flash_frequency": 0.6,
        "shake_intensity": 0.8,
        "zoom_aggression": 0.7,
        "color_warmth": 0.5,
        "beat_sync_strictness": 0.9,
        "variety": 0.5,
        "arc_enabled": True,
    },
    "cinematic": {
        "pacing": 0.3,
        "effect_intensity": 0.5,
        "slowmo_bias": 0.8,
        "flash_frequency": 0.1,
        "shake_intensity": 0.1,
        "zoom_aggression": 0.3,
        "color_warmth": 0.8,
        "beat_sync_strictness": 0.5,
        "variety": 0.3,
        "arc_enabled": True,
    },
    "hyperpop": {
        "pacing": 1.0,
        "effect_intensity": 1.0,
        "slowmo_bias": 0.3,
        "flash_frequency": 0.8,
        "shake_intensity": 0.9,
        "zoom_aggression": 0.9,
        "color_warmth": 0.4,
        "beat_sync_strictness": 0.7,
        "variety": 1.0,
        "arc_enabled": True,
    },
    "chill": {
        "pacing": 0.2,
        "effect_intensity": 0.3,
        "slowmo_bias": 0.4,
        "flash_frequency": 0.0,
        "shake_intensity": 0.0,
        "zoom_aggression": 0.2,
        "color_warmth": 0.7,
        "beat_sync_strictness": 0.3,
        "variety": 0.2,
        "arc_enabled": True,
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)  # type: ignore[arg-type]
        else:
            out[k] = v
    return out


def resolve_creative_config(*, style_preset: str, creative_config: dict[str, Any] | None = None) -> dict[str, Any]:
    preset = PRESETS.get(style_preset, PRESETS["aggressive"])
    return _deep_merge(preset, creative_config or {})
