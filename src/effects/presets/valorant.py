from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class EffectPreset:
    zoom: dict[str, float | str]
    shake: dict[str, float | int]
    color_grading: dict[str, float | str | None]


PRESETS: dict[Literal["intro", "build", "climax", "outro"], EffectPreset] = {
    "intro": EffectPreset(
        zoom={"max_zoom": 1.15, "duration_sec": 0.25, "easing": "ease_out_quad", "center": "screen_center"},
        shake={"amplitude_px": 2, "decay_rate": 0.9, "duration_frames": 6},
        color_grading={"saturation": 1.1, "contrast": 1.05, "brightness": 0.01, "lut_file": None},
    ),
    "build": EffectPreset(
        zoom={"max_zoom": 1.25, "duration_sec": 0.3, "easing": "ease_out_quad", "center": "screen_center"},
        shake={"amplitude_px": 4, "decay_rate": 0.85, "duration_frames": 8},
        color_grading={"saturation": 1.15, "contrast": 1.1, "brightness": 0.015, "lut_file": None},
    ),
    "climax": EffectPreset(
        zoom={"max_zoom": 1.35, "duration_sec": 0.35, "easing": "ease_out_quad", "center": "screen_center"},
        shake={"amplitude_px": 6, "decay_rate": 0.8, "duration_frames": 10},
        color_grading={"saturation": 1.25, "contrast": 1.15, "brightness": 0.02, "lut_file": None},
    ),
    "outro": EffectPreset(
        zoom={"max_zoom": 1.1, "duration_sec": 0.2, "easing": "ease_out_quad", "center": "screen_center"},
        shake={"amplitude_px": 1, "decay_rate": 0.95, "duration_frames": 4},
        color_grading={"saturation": 1.05, "contrast": 1.02, "brightness": 0.005, "lut_file": None},
    ),
}


def get_preset(arc_phase: str, intensity_bias: float = 0.7) -> EffectPreset:
    base = PRESETS.get(arc_phase, PRESETS["build"])  # type: ignore[call-overload]
    if abs(intensity_bias - 0.7) < 0.01:
        return base
    mod = 1 + (intensity_bias - 0.7) * 0.3
    shake_mul = 1 + (intensity_bias - 0.7) * 0.5
    color_mul = 1 + (intensity_bias - 0.7) * 0.2
    shake_out: dict[str, float | int] = {}
    for k, v in base.shake.items():
        nv = float(v) * shake_mul
        shake_out[k] = int(round(nv)) if k in ("amplitude_px", "duration_frames") else nv
    return EffectPreset(
        zoom={k: v * mod if isinstance(v, (int, float)) else v for k, v in base.zoom.items()},
        shake=shake_out,
        color_grading={
            k: v * color_mul if isinstance(v, (int, float)) else v for k, v in base.color_grading.items()
        },
    )
