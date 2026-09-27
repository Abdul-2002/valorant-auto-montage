"""Montage-level overlays on the assembled timeline: light leaks, flare streaks, title, callouts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from src.ai.schema import MontageScript
from src.config.models import OverlaysConfig
from src.effects.envelopes import decay_envelope
from src.effects.text_sprites import composite, text_sprite
from src.pipeline.beat_analyzer import BeatMap

_LEAK_SEC = 1.1
_FLARE_SEC = 0.28
_CALLOUT_SEC = 1.0
_LOW_RES = (192, 108)
_LEAK_COLORS = ((255, 140, 60), (255, 70, 150), (70, 190, 255))
CALLOUT_TEXT = {2: "DOUBLE KILL", 3: "TRIPLE KILL", 4: "QUADRA KILL", 5: "ACE"}
_WHITE, _CYAN, _GOLD = (255, 255, 255), (80, 200, 255), (255, 190, 70)


@dataclass(frozen=True)
class OverlayPlan:
    kill_times: tuple[float, ...]
    leak_times: tuple[float, ...]
    callouts: tuple[tuple[float, str], ...]
    title: str
    credit: str
    title_sec: float


def build_overlay_plan(
    *, script: MontageScript, beat_map: BeatMap | None, cfg: OverlaysConfig, song_title: str, phase_sec: float
) -> OverlayPlan:
    """Montage-time events: every kill, section changes + cinematic kills (leaks), multi-kills (callouts)."""
    kills: list[float] = []
    leaks: list[float] = []
    callouts: list[tuple[float, str]] = []
    for c in script.clips:
        start = float(c.output_start_sec or 0.0) - phase_sec
        rel = [start + float(k) for k in c.kill_output_times_sec]
        kills.extend(rel)
        if c.recipe == "cinematic" and rel:
            leaks.append(rel[-1])
        if cfg.multi_kill_callouts and len(rel) >= 2:
            callouts.append((rel[-1], CALLOUT_TEXT.get(len(rel), f"{len(rel)}K")))
    for s in (beat_map.sections if beat_map is not None else None) or []:
        t = float(s.start_sec) - phase_sec
        if t > 0.5 and s.section_type in ("chorus", "drop", "inst", "solo"):
            leaks.append(t)
    return OverlayPlan(
        kill_times=tuple(kills),
        leak_times=tuple(sorted(leaks)),
        callouts=tuple(callouts),
        title=cfg.title_text,
        credit=song_title if cfg.song_credit else "",
        title_sec=cfg.title_sec,
    )


def _light_leak(frame: np.ndarray, u: float, seed: int, strength: float) -> np.ndarray:
    """Soft colored blob sweeping across the frame, screen-blended."""
    lw, lh = _LOW_RES
    yy, xx = np.mgrid[0:lh, 0:lw].astype(np.float32)
    cx = (-0.2 + 1.4 * u) * lw
    cy = (0.25 if seed % 2 else 0.7) * lh
    blob = np.exp(-(((xx - cx) / (0.35 * lw)) ** 2 + ((yy - cy) / (0.45 * lh)) ** 2))
    color = np.asarray(_LEAK_COLORS[seed % len(_LEAK_COLORS)], dtype=np.float32) / 255.0
    leak = cv2.resize(blob[..., None] * color, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_LINEAR)
    env = float(np.sin(np.pi * u)) * strength
    img = frame.astype(np.float32) / 255.0
    return ((1.0 - (1.0 - img) * (1.0 - leak * env)) * 255.0).astype(np.uint8)


def _flare_streak(frame: np.ndarray, e: float, strength: float) -> np.ndarray:
    """Anamorphic horizontal streak from the brightest pixels (muzzle flash, kill flash)."""
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (w // 4, h // 4), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    luma = small @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    bright = np.clip((luma - 0.8) / 0.2, 0.0, 1.0)[..., None] * np.array([0.6, 0.8, 1.0], dtype=np.float32)
    streak = cv2.blur(bright, (w // 8 | 1, 1))
    streak = cv2.resize(streak, (w, h), interpolation=cv2.INTER_LINEAR)
    img = frame.astype(np.float32) / 255.0
    return (np.clip(img + streak * (strength * e), 0.0, 1.0) * 255.0).astype(np.uint8)


def _title_alpha(t: float, dur: float) -> tuple[float, float]:
    """(alpha, scale): pop in over 0.25s, hold, fade out over the last 0.4s."""
    if t < 0.0 or t > dur:
        return 0.0, 1.0
    pop = min(1.0, t / 0.25)
    fade = min(1.0, (dur - t) / 0.4)
    return min(pop, fade), 1.15 - 0.15 * pop


def _draw_text(frame: np.ndarray, t: float, plan: OverlayPlan, font_path: str) -> np.ndarray:
    h, w = frame.shape[:2]
    alpha, scale = _title_alpha(t, plan.title_sec)
    if alpha > 0.0 and plan.title:
        frame = composite(frame, text_sprite(plan.title, size=84, color=_WHITE, glow=_CYAN, font_path=font_path),
                          cx=w / 2, cy=h * 0.40, alpha=alpha, scale=scale)
    credit_alpha, _ = _title_alpha(t - 0.35, plan.title_sec - 0.35)
    if credit_alpha > 0.0 and plan.credit:
        frame = composite(frame, text_sprite(plan.credit, size=34, color=_WHITE, glow=_GOLD, font_path=font_path),
                          cx=w / 2, cy=h * 0.49, alpha=credit_alpha)
    for at, text in plan.callouts:
        rel = t - at
        if 0.0 <= rel <= _CALLOUT_SEC:
            pop = min(1.0, rel / 0.12)
            fade = min(1.0, (_CALLOUT_SEC - rel) / 0.25)
            frame = composite(frame, text_sprite(text, size=78, color=_WHITE, glow=_GOLD, font_path=font_path),
                              cx=w / 2, cy=h * 0.28, alpha=min(pop, fade), scale=1.35 - 0.35 * pop)
    return frame


def apply_montage_overlays(clip: Any, plan: OverlayPlan, cfg: OverlaysConfig) -> Any:
    if not cfg.enabled:
        return clip

    def transform(get_frame, t: float):
        frame = get_frame(t)
        t = float(t)
        if cfg.light_leaks:
            for i, lt in enumerate(plan.leak_times):
                if lt <= t < lt + _LEAK_SEC:
                    frame = _light_leak(frame, (t - lt) / _LEAK_SEC, i, cfg.light_leak_strength)
        if cfg.flare_streaks:
            e = max((decay_envelope(t, k, _FLARE_SEC) for k in plan.kill_times), default=0.0)
            if e > 0.02:
                frame = _flare_streak(frame, e, cfg.flare_strength)
        return _draw_text(frame, t, plan, cfg.font_path)

    return clip.transform(transform)
