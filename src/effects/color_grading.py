"""Contrast and saturation grade. CUDA path matches OpenCV's 8-bit HSV exactly."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.registry import register_clip_effect

_HSV_SHIFT = 12
_HSV_ROUND = 1 << (_HSV_SHIFT - 1)
_TABLES: dict[str, tuple[Any, Any]] = {}


def _grade_frame_cpu(frame: np.ndarray, contrast: float, brightness: float, saturation: float) -> np.ndarray:
    img = frame.astype(np.float32) / 255.0
    img = np.clip((img - 0.5) * contrast + 0.5 + brightness, 0.0, 1.0)
    hsv = cv2.cvtColor((img * 255).astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * saturation, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)


def _hsv_tables(device: Any) -> tuple[Any, Any]:
    import torch

    key = str(device)
    cached = _TABLES.get(key)
    if cached is not None:
        return cached
    hdiv = [0 if i == 0 else int((180 << _HSV_SHIFT) / (6.0 * i) + 0.5) for i in range(256)]
    sdiv = [0 if i == 0 else int((255 << _HSV_SHIFT) / float(i) + 0.5) for i in range(256)]
    tables = (
        torch.tensor(hdiv, device=device, dtype=torch.int32),
        torch.tensor(sdiv, device=device, dtype=torch.int32),
    )
    _TABLES[key] = tables
    return tables


def _rgb_to_hsv(q: Any, hdiv: Any, sdiv: Any) -> tuple[Any, Any, Any]:
    import torch

    r, g, b = q.unbind(-1)
    value, idx = q.max(dim=-1)
    diff = value - q.min(dim=-1).values
    hue_raw = torch.where(idx == 0, g - b, torch.where(idx == 1, b - r + 2 * diff, r - g + 4 * diff))
    hue = (hue_raw * hdiv[diff.clamp(0, 255)] + _HSV_ROUND) >> _HSV_SHIFT
    hue = torch.where(hue < 0, hue + 180, hue)
    hue = torch.where(diff == 0, torch.zeros_like(hue), hue)
    sat = (diff * sdiv[value.clamp(0, 255)] + _HSV_ROUND) >> _HSV_SHIFT
    sat = torch.where(value == 0, torch.zeros_like(sat), sat)
    return hue, sat, value


def _hsv_to_rgb(hue: Any, sat: Any, value: Any) -> Any:
    import torch

    sector_f = hue.float() / 30.0
    sector = sector_f.floor().long() % 6
    frac = sector_f - sector.float()
    v = value.float() / 255.0
    s = sat.float() / 255.0
    tab = (
        v,
        v * (1.0 - s),
        v * (1.0 - s * frac),
        v * (1.0 - s * (1.0 - frac)),
    )
    # OpenCV sector map, written out as RGB.
    red = (tab[0], tab[2], tab[1], tab[1], tab[3], tab[0])
    green = (tab[3], tab[0], tab[0], tab[2], tab[1], tab[1])
    blue = (tab[1], tab[1], tab[3], tab[0], tab[0], tab[2])
    out = torch.stack([torch.zeros_like(v), torch.zeros_like(v), torch.zeros_like(v)], dim=-1)
    for i in range(6):
        mask = sector == i
        out[..., 0] = torch.where(mask, red[i], out[..., 0])
        out[..., 1] = torch.where(mask, green[i], out[..., 1])
        out[..., 2] = torch.where(mask, blue[i], out[..., 2])
    return out.mul_(255.0).round_().clamp_(0, 255).to(torch.uint8)


def _grade_frame_cuda(frame: np.ndarray, contrast: float, brightness: float, saturation: float) -> np.ndarray:
    import torch

    device = torch.device("cuda")
    hdiv, sdiv = _hsv_tables(device)
    x = torch.from_numpy(np.ascontiguousarray(frame)).to(device, non_blocking=True).float().div_(255.0)
    x = ((x - 0.5) * contrast + 0.5 + brightness).clamp_(0.0, 1.0)
    q = (x * 255.0).clamp_(0, 255).to(torch.int32)
    hue, sat, value = _rgb_to_hsv(q, hdiv, sdiv)
    sat = (sat.float() * saturation).clamp_(0, 255).to(torch.int32)
    return _hsv_to_rgb(hue, sat, value).cpu().numpy()


def grade_frame(frame: np.ndarray, contrast: float, brightness: float, saturation: float) -> np.ndarray:
    """Grade one RGB frame. Uses CUDA when available; the result matches the CPU path."""
    try:
        import torch

        if torch.cuda.is_available():
            return _grade_frame_cuda(frame, contrast, brightness, saturation)
    except ImportError:
        pass
    return _grade_frame_cpu(frame, contrast, brightness, saturation)


@register_clip_effect("color_grading")
@dataclass
class ColorGradingEffect(ClipEffect):
    enabled: bool = True
    saturation: float = 1.3
    contrast: float = 1.1
    brightness: float = 0.02
    lut_file: str | None = None

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled:
            return clip
        contrast, brightness, saturation = self.contrast, self.brightness, self.saturation

        def transform(get_frame, t: float):
            return grade_frame(get_frame(t), contrast, brightness, saturation)

        return clip.transform(transform)
