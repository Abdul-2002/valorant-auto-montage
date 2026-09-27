"""Pre-rendered RGBA text sprites (Pillow) with stroke + glow, and alpha compositing helpers."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

_FONT_CANDIDATES = (
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)
# The 9:16 export is a 608 px center crop of 1080p; text must fit inside it.
SAFE_WIDTH_PX = 560


@lru_cache(maxsize=8)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in ([path] if path else []) + list(_FONT_CANDIDATES):
        if candidate and Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    log.warning("text_sprites: no TTF font found; falling back to Pillow default")
    return ImageFont.load_default()


def _fit_size(text: str, font_path: str, size: int, max_width: int) -> int:
    while size > 12:
        left, _, right, _ = _font(font_path, size).getbbox(text)
        if right - left <= max_width:
            return size
        size -= 2
    return size


@lru_cache(maxsize=32)
def text_sprite(
    text: str, *, size: int, color: tuple[int, int, int], glow: tuple[int, int, int], font_path: str = ""
) -> np.ndarray:
    """RGBA uint8 sprite no wider than the 9:16 safe width."""
    font = _font(font_path, _fit_size(text, font_path, size, SAFE_WIDTH_PX))
    left, top, right, bottom = font.getbbox(text)
    pad = 24
    w, h = right - left + 2 * pad, bottom - top + 2 * pad
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((pad - left, pad - top), text, font=font, fill=(*color, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
    sprite = np.asarray(img).astype(np.float32)
    halo = cv2.GaussianBlur(sprite[:, :, 3], (0, 0), 8.0)
    glow_layer = np.zeros_like(sprite)
    glow_layer[:, :, :3] = np.asarray(glow, dtype=np.float32)
    glow_layer[:, :, 3] = halo * 0.8
    a = sprite[:, :, 3:] / 255.0
    out = sprite.copy()
    out[:, :, :3] = sprite[:, :, :3] * a + glow_layer[:, :, :3] * (1.0 - a)
    out[:, :, 3] = np.maximum(sprite[:, :, 3], glow_layer[:, :, 3])
    return np.clip(out, 0, 255).astype(np.uint8)


def composite(frame: np.ndarray, sprite: np.ndarray, *, cx: float, cy: float, alpha: float, scale: float = 1.0) -> np.ndarray:
    """Alpha-blend ``sprite`` centered at (cx, cy) pixels; clips at frame edges."""
    if alpha <= 0.01:
        return frame
    if abs(scale - 1.0) > 1e-3:
        sprite = cv2.resize(sprite, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    sh, sw = sprite.shape[:2]
    fh, fw = frame.shape[:2]
    x0, y0 = int(round(cx - sw / 2)), int(round(cy - sh / 2))
    fx0, fy0, fx1, fy1 = max(0, x0), max(0, y0), min(fw, x0 + sw), min(fh, y0 + sh)
    if fx1 <= fx0 or fy1 <= fy0:
        return frame
    part = sprite[fy0 - y0 : fy1 - y0, fx0 - x0 : fx1 - x0].astype(np.float32)
    a = (part[:, :, 3:] / 255.0) * float(alpha)
    out = frame.copy()
    roi = out[fy0:fy1, fx0:fx1].astype(np.float32)
    out[fy0:fy1, fx0:fx1] = (roi * (1.0 - a) + part[:, :, :3] * a).astype(np.uint8)
    return out
