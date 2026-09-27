"""Procedural color look written as a .cube 3D LUT (applied by ffmpeg lut3d at encode)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

_SHADOW_TINT = np.array([-0.02, 0.05, 0.09])  # teal
_HIGHLIGHT_TINT = np.array([0.08, 0.03, -0.05])  # warm orange
_CONTRAST = 0.35
_SATURATION = 1.12


def teal_orange(rgb: np.ndarray) -> np.ndarray:
    """Gameplay-montage look: S-curve contrast, teal shadows, warm highlights, mild saturation."""
    s_curve = rgb * rgb * (3.0 - 2.0 * rgb)
    out = rgb * (1.0 - _CONTRAST) + s_curve * _CONTRAST
    luma = (0.2126 * out[..., 0] + 0.7152 * out[..., 1] + 0.0722 * out[..., 2])[..., None]
    out = out + _SHADOW_TINT * (1.0 - luma) ** 2 + _HIGHLIGHT_TINT * luma**2
    luma = (0.2126 * out[..., 0] + 0.7152 * out[..., 1] + 0.0722 * out[..., 2])[..., None]
    return np.clip(luma + (out - luma) * _SATURATION, 0.0, 1.0)


def write_cube_lut(path: Path, *, size: int = 33) -> Path:
    """Write the teal/orange look as an Adobe .cube file (red varies fastest)."""
    axis = np.linspace(0.0, 1.0, size)
    b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
    table = teal_orange(np.stack([r, g, b], axis=-1)).reshape(-1, 3)
    lines = [f"LUT_3D_SIZE {size}"] + [f"{x:.6f} {y:.6f} {z:.6f}" for x, y, z in table]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
