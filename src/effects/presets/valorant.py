from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class EffectPreset:
    velocity: dict[str, float | str]
    zoom: dict[str, float | str]
    shake: dict[str, float | int]
    color_grading: dict[str, float | str | None]
    transition: dict[str, str | float]


PRESETS: dict[Literal["intro", "build", "climax", "outro"], EffectPreset] = {
    "intro": EffectPreset(
        velocity={
            "kill_slowmo_factor": 0.6,
            "kill_slowmo_duration_sec": 0.4,
            "transition_speedup_factor": 1.3,
            "easing": "ease_in_out_cubic",
        },
        zoom={
            "max_zoom": 1.15,
            "duration_sec": 0.25,
            "easing": "ease_out_quad",
            "center": "screen_center",
        },
        shake={"amplitude_px": 2, "decay_rate": 0.9, "duration_frames": 6},
        color_grading={"saturation": 1.1, "contrast": 1.05, "brightness": 0.01, "lut_file": None},
        transition={"type": "hard_cut", "duration_sec": 0.1},
    ),
    "build": EffectPreset(
        velocity={
            "kill_slowmo_factor": 0.5,
            "kill_slowmo_duration_sec": 0.5,
            "transition_speedup_factor": 1.5,
            "easing": "ease_in_out_cubic",
        },
        zoom={
            "max_zoom": 1.25,
            "duration_sec": 0.3,
            "easing": "ease_out_quad",
            "center": "screen_center",
        },
        shake={"amplitude_px": 4, "decay_rate": 0.85, "duration_frames": 8},
        color_grading={"saturation": 1.15, "contrast": 1.1, "brightness": 0.015, "lut_file": None},
        transition={"type": "flash_white", "duration_sec": 0.05},
    ),
    "climax": EffectPreset(
        velocity={
            "kill_slowmo_factor": 0.4,
            "kill_slowmo_duration_sec": 0.6,
            "transition_speedup_factor": 1.8,
            "easing": "ease_in_out_cubic",
        },
        zoom={
            "max_zoom": 1.35,
            "duration_sec": 0.35,
            "easing": "ease_out_quad",
            "center": "screen_center",
        },
        shake={"amplitude_px": 6, "decay_rate": 0.8, "duration_frames": 10},
        color_grading={"saturation": 1.25, "contrast": 1.15, "brightness": 0.02, "lut_file": None},
        transition={"type": "flash_white", "duration_sec": 0.05},
    ),
    "outro": EffectPreset(
        velocity={
            "kill_slowmo_factor": 0.7,
            "kill_slowmo_duration_sec": 0.3,
            "transition_speedup_factor": 1.2,
            "easing": "ease_in_out_cubic",
        },
        zoom={
            "max_zoom": 1.1,
            "duration_sec": 0.2,
            "easing": "ease_out_quad",
            "center": "screen_center",
        },
        shake={"amplitude_px": 1, "decay_rate": 0.95, "duration_frames": 4},
        color_grading={"saturation": 1.05, "contrast": 1.02, "brightness": 0.005, "lut_file": None},
        transition={"type": "dissolve", "duration_sec": 0.2},
    ),
}


def get_preset(arc_phase: str, intensity_bias: float = 0.7) -> EffectPreset:
    base = PRESETS.get(arc_phase, PRESETS["build"])
    if abs(intensity_bias - 0.7) < 0.01:
        return base
    mod = 1 + (intensity_bias - 0.7) * 0.3
    shake_mul = 1 + (intensity_bias - 0.7) * 0.5
    color_mul = 1 + (intensity_bias - 0.7) * 0.2
    shake_out: dict[str, float | int] = {}
    for k, v in base.shake.items():
        if not isinstance(v, (int, float)):
            shake_out[k] = v
            continue
        nv = float(v) * shake_mul
        if k in ("amplitude_px", "duration_frames"):
            shake_out[k] = int(round(nv))
        else:
            shake_out[k] = nv
    return EffectPreset(
        velocity={k: v * mod if isinstance(v, (int, float)) else v for k, v in base.velocity.items()},
        zoom={k: v * mod if isinstance(v, (int, float)) else v for k, v in base.zoom.items()},
        shake=shake_out,
        color_grading={
            k: v * color_mul if isinstance(v, (int, float)) else v for k, v in base.color_grading.items()
        },
        transition=base.transition,
    )
