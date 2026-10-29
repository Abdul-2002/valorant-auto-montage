"""Kill-anchored glitter: sparkle flakes, star glints and energy slashes (reference montage look).

Screen-space, drawn at half resolution. Particles are seeded per (seed, kill) so
re-renders are identical and clips sharing a variant still lay out differently.
Coordinates are in frame-height units: x in [0, aspect], y in [0, 1].
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.highlight_bloom import screen_add
from src.effects.registry import register_clip_effect

GLITTER_VARIANTS: tuple[str, ...] = ("sparkle_field", "star_burst", "streak")
# RGB: white, pink, gold, ice.
_PALETTE = np.array([[1.0, 1.0, 1.0], [1.0, 0.62, 0.88], [1.0, 0.86, 0.5], [0.6, 0.88, 1.0]], dtype=np.float32)
_SLASH_TINTS = np.array([[1.0, 0.3, 0.85], [0.3, 0.9, 1.0]], dtype=np.float32)
_ATTACK_SEC = 0.04
_HOLD_FRAC = 0.4
_TWINKLE_HZ = 9.0
_SWEEP_SEC = 0.22
_SLASH_POINTS = 24
_REFERENCE_HALF_HEIGHT = 540.0


@dataclass(frozen=True)
class Burst:
    pos: np.ndarray
    vel: np.ndarray
    size: np.ndarray
    color: np.ndarray
    phase: np.ndarray
    birth: np.ndarray
    glint: np.ndarray
    drag: float = 0.0
    # Slash centre-line (points x 2) and RGB tint; streak variant only.
    slash: tuple[np.ndarray, np.ndarray] | None = None


def _common(rng: np.random.Generator, n: int, palette_p: list[float], glint_p: float) -> dict[str, np.ndarray]:
    return {
        "size": rng.uniform(1.0, 3.2, n),
        "color": _PALETTE[rng.choice(len(_PALETTE), size=n, p=palette_p)],
        "phase": rng.uniform(0.0, 2.0 * np.pi, n),
        "glint": rng.random(n) < glint_p,
    }


def _sparkle_field(rng: np.random.Generator, aspect: float, density: float) -> Burst:
    n = max(1, int(300 * density))
    pos = np.column_stack([rng.uniform(0.0, aspect, n), rng.uniform(-0.05, 1.0, n)])
    vel = np.column_stack([rng.normal(0.0, 0.04, n), rng.uniform(0.03, 0.12, n)])
    return Burst(pos=pos, vel=vel, birth=np.zeros(n), **_common(rng, n, [0.62, 0.3, 0.05, 0.03], 0.15))


def _star_burst(rng: np.random.Generator, aspect: float, density: float) -> Burst:
    n = max(1, int(120 * density))
    angle, speed = rng.uniform(0.0, 2.0 * np.pi, n), rng.uniform(0.3, 1.1, n)
    pos = np.array([aspect / 2.0, 0.5]) + rng.normal(0.0, 0.015, (n, 2))
    vel = np.column_stack([np.cos(angle), np.sin(angle)]) * speed[:, None]
    common = _common(rng, n, [0.5, 0.1, 0.35, 0.05], 0.3)
    return Burst(pos=pos, vel=vel, birth=np.zeros(n), drag=3.0, **common)


def _streak(rng: np.random.Generator, aspect: float, density: float) -> Burst:
    """Curved slash across the lower-middle frame (the viewmodel area) leaving flakes behind."""
    n = max(1, int(110 * density))
    start = np.array([rng.uniform(0.1, 0.35) * aspect, rng.uniform(0.75, 0.95)])
    end = np.array([rng.uniform(0.6, 0.9) * aspect, rng.uniform(0.25, 0.5)])
    bow = np.array([end[1] - start[1], start[0] - end[0]]) * rng.uniform(0.2, 0.4)
    s = np.linspace(0.0, 1.0, _SLASH_POINTS)[:, None]
    line = (1 - s) ** 2 * start + 2 * s * (1 - s) * ((start + end) / 2.0 + bow) + s**2 * end
    k = rng.integers(0, _SLASH_POINTS, n)
    pos = line[k] + rng.normal(0.0, 0.025, (n, 2))
    tint = _SLASH_TINTS[int(rng.integers(0, len(_SLASH_TINTS)))]
    common = _common(rng, n, [0.5, 0.3, 0.0, 0.2], 0.15)
    return Burst(pos=pos, vel=rng.normal(0.0, 0.05, (n, 2)), birth=k / _SLASH_POINTS * _SWEEP_SEC, slash=(line, tint), **common)


_SPAWNERS = {"sparkle_field": _sparkle_field, "star_burst": _star_burst, "streak": _streak}


def spawn_burst(variant: str, rng: np.random.Generator, *, aspect: float, density: float) -> Burst:
    """Particles for one kill; ``variant`` must be in GLITTER_VARIANTS."""
    return _SPAWNERS[variant](rng, aspect, density)


def _fade(u: float, life: float) -> float:
    return float(np.clip((1.0 - u / life) / (1.0 - _HOLD_FRAC), 0.0, 1.0))


def _draw_slash(layer: np.ndarray, burst: Burst, u: float, life: float, intensity: float) -> None:
    line, tint = burst.slash  # type: ignore[misc]
    h = layer.shape[0]
    head = int(min(1.0, u / _SWEEP_SEC) * (_SLASH_POINTS - 1))
    tail = int(max(0.0, u / _SWEEP_SEC - 0.5) * (_SLASH_POINTS - 1))
    alpha = intensity * min(1.0, u / _ATTACK_SEC) * _fade(u, 0.6 * life)
    pts = (line * h).astype(int)
    for j in range(tail, head):
        taper = 0.35 + 0.65 * (j - tail + 1) / max(1, head - tail)
        color = tuple(float(c) * alpha for c in tint)
        p0, p1 = (int(pts[j][0]), int(pts[j][1])), (int(pts[j + 1][0]), int(pts[j + 1][1]))
        cv2.line(layer, p0, p1, color, max(2, int(0.03 * h * taper)), cv2.LINE_AA)


def _draw_flake(layer: np.ndarray, xy: np.ndarray, r: int, col: tuple[float, ...], glint: bool) -> None:
    x, y = int(xy[0]), int(xy[1])
    cv2.circle(layer, (x, y), r, col, -1, cv2.LINE_AA)
    if glint:
        arm = r * 6
        cv2.line(layer, (x - arm, y), (x + arm, y), col, 1, cv2.LINE_AA)
        cv2.line(layer, (x, y - arm), (x, y + arm), col, 1, cv2.LINE_AA)


def draw_burst(layer: np.ndarray, burst: Burst, u: float, *, life: float, intensity: float) -> None:
    """Paint ``burst`` at ``u`` seconds after its kill onto a float RGB layer."""
    h = layer.shape[0]
    if burst.slash is not None:
        _draw_slash(layer, burst, u, life, intensity)
    local = u - burst.birth
    twinkle = 0.6 + 0.4 * np.sin(2.0 * np.pi * _TWINKLE_HZ * local + burst.phase)
    attack = np.where(local >= 0.0, np.clip(local / _ATTACK_SEC, 0.0, 1.0), 0.0)
    alpha = intensity * _fade(u, life) * attack * twinkle
    t = np.maximum(local, 0.0)[:, None]
    travel = burst.vel * ((1.0 - np.exp(-burst.drag * t)) / burst.drag if burst.drag > 0.0 else t)
    xy = (burst.pos + travel) * h
    radius = np.maximum(1, (burst.size * h / _REFERENCE_HALF_HEIGHT).astype(int))
    for p, r, c, a, g in zip(xy, radius, burst.color, alpha, burst.glint):
        if a >= 0.02:
            _draw_flake(layer, p, int(r), tuple(float(v) * float(a) for v in c), bool(g))


def composite_glitter(frame: np.ndarray, layer: np.ndarray) -> np.ndarray:
    """Glow the half-res layer and screen it over the full-res RGB frame."""
    fh, fw = frame.shape[:2]
    glow = layer + 0.9 * cv2.GaussianBlur(layer, (0, 0), 2.0) + 0.6 * cv2.GaussianBlur(layer, (0, 0), 7.0)
    over = cv2.resize(np.clip(glow, 0.0, 1.0), (fw, fh), interpolation=cv2.INTER_LINEAR)
    out = screen_add(frame.astype(np.float32) / 255.0, over, 1.0)
    return (out * 255.0 + 0.5).astype(np.uint8)


@register_clip_effect("glitter")
@dataclass
class GlitterEffect(ClipEffect):
    enabled: bool = True
    variant: str = "sparkle_field"
    seed: int = 0
    life_sec: float = 0.85
    density: float = 1.0
    intensity: float = 0.9

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        anchors = tuple(float(a) for a in ctx.kill_timestamps) or (
            (float(ctx.kill_timestamp),) if ctx.kill_timestamp is not None else ()
        )
        if not self.enabled or not anchors or self.variant not in GLITTER_VARIANTS:
            return clip
        aspect = float(ctx.resolution[0]) / float(ctx.resolution[1])
        bursts = [
            (a, spawn_burst(self.variant, np.random.default_rng((int(self.seed), k)), aspect=aspect, density=self.density))
            for k, a in enumerate(anchors)
        ]
        life, intensity = float(self.life_sec), float(self.intensity)

        def transform(get_frame, t: float):
            frame = get_frame(t)
            active = [(a, b) for a, b in bursts if 0.0 <= float(t) - a < life]
            if not active:
                return frame
            layer = np.zeros((frame.shape[0] // 2, frame.shape[1] // 2, 3), dtype=np.float32)
            for a, b in active:
                draw_burst(layer, b, float(t) - a, life=life, intensity=intensity)
            return composite_glitter(frame, layer)

        return clip.transform(transform)
