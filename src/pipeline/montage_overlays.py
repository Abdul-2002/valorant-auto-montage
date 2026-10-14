"""Montage-level overlays: light leaks, flares, kill/burst callouts, lyrics, title."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import cv2
import numpy as np

from src.ai.schema import MontageScript
from src.config.models import OverlaysConfig
from src.effects.envelopes import decay_envelope
from src.effects.text_sprites import composite, text_sprite, text_sprite_3d
from src.pipeline.beat_analyzer import BeatMap

_LEAK_SEC = 1.1
_FLARE_SEC = 0.28
_KILL_SEC = 0.55
_BURST_SEC = 1.05
_LYRIC_SEC = 1.4
_LOW_RES = (192, 108)
_LEAK_COLORS = ((255, 140, 60), (255, 70, 150), (70, 190, 255))

# Burst size → Valorant-style callout (clip-local multi-kill).
BURST_TEXT = {2: "DOUBLE KILL", 3: "TRIPLE KILL", 4: "QUADRA KILL", 5: "ACE"}
TextKind = Literal["title", "credit", "kill", "burst", "lyric"]

_STYLE: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], int, float]] = {
    # color, glow, size, y_frac
    "title": ((255, 255, 255), (80, 200, 255), 72, 0.40),
    "credit": ((255, 255, 255), (255, 190, 70), 32, 0.48),
    "kill": ((255, 255, 255), (255, 60, 80), 64, 0.26),
    "burst": ((255, 255, 255), (255, 190, 40), 82, 0.24),
    "lyric": ((255, 255, 255), (120, 220, 255), 56, 0.72),
}


@dataclass(frozen=True)
class TextEvent:
    at_sec: float
    text: str
    kind: TextKind
    hold_sec: float


@dataclass(frozen=True)
class OverlayPlan:
    kill_times: tuple[float, ...]
    leak_times: tuple[float, ...]
    texts: tuple[TextEvent, ...]


def _burst_label(n: int) -> str:
    return BURST_TEXT.get(n, f"{n}K")


def build_overlay_plan(
    *,
    script: MontageScript,
    beat_map: BeatMap | None,
    cfg: OverlaysConfig,
    song_title: str,
    phase_sec: float,
    lyric_events: list[tuple[float, str]] | None = None,
) -> OverlayPlan:
    """Montage-time overlays: per-kill flashes, burst/ACE on multi-kills, optional lyrics."""
    kills: list[float] = []
    leaks: list[float] = []
    texts: list[TextEvent] = []

    if cfg.title_text.strip():
        texts.append(TextEvent(0.0, cfg.title_text.strip(), "title", float(cfg.title_sec)))
    if cfg.song_credit and song_title.strip():
        texts.append(TextEvent(0.35, song_title.strip(), "credit", max(1.0, float(cfg.title_sec) - 0.35)))

    for c in script.clips:
        start = float(c.output_start_sec or 0.0) - phase_sec
        rel = [start + float(k) for k in (c.kill_output_times_sec or [])]
        if not rel:
            continue
        kills.extend(rel)
        if c.recipe == "cinematic":
            leaks.append(rel[-1])

        n = len(rel)
        if cfg.multi_kill_callouts and n >= 2:
            # Burst label on the last kill of the group only.
            texts.append(TextEvent(rel[-1], _burst_label(n), "burst", _BURST_SEC))
            if cfg.per_kill_callouts:
                for t in rel[:-1]:
                    texts.append(TextEvent(t, "KILL", "kill", _KILL_SEC))
        elif cfg.per_kill_callouts:
            for t in rel:
                texts.append(TextEvent(t, "KILL", "kill", _KILL_SEC))

    for s in (beat_map.sections if beat_map is not None else None) or []:
        t = float(s.start_sec) - phase_sec
        if t > 0.5 and s.section_type in ("chorus", "drop", "inst", "solo"):
            leaks.append(t)

    if cfg.lyrics_overlays and lyric_events:
        for t, line in lyric_events:
            at = float(t) - phase_sec
            if at < -0.05:
                continue
            texts.append(TextEvent(at, str(line).strip().upper(), "lyric", _LYRIC_SEC))

    return OverlayPlan(
        kill_times=tuple(kills),
        leak_times=tuple(sorted(set(round(x, 3) for x in leaks))),
        texts=tuple(texts),
    )


def _light_leak(frame: np.ndarray, u: float, seed: int, strength: float) -> np.ndarray:
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
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (w // 4, h // 4), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    luma = small @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    bright = np.clip((luma - 0.8) / 0.2, 0.0, 1.0)[..., None] * np.array([0.6, 0.8, 1.0], dtype=np.float32)
    streak = cv2.blur(bright, (w // 8 | 1, 1))
    streak = cv2.resize(streak, (w, h), interpolation=cv2.INTER_LINEAR)
    img = frame.astype(np.float32) / 255.0
    return (np.clip(img + streak * (strength * e), 0.0, 1.0) * 255.0).astype(np.uint8)


def _event_alpha(rel: float, hold: float) -> tuple[float, float]:
    """Pop-in, hold, fade-out → (alpha, scale)."""
    if rel < 0.0 or rel > hold:
        return 0.0, 1.0
    pop = min(1.0, rel / 0.12)
    fade = min(1.0, (hold - rel) / 0.28)
    alpha = min(pop, fade)
    # Burst punches larger; kills snap slightly overscale.
    scale = 1.0 + 0.28 * (1.0 - pop)
    return alpha, scale


def _draw_texts(frame: np.ndarray, t: float, plan: OverlayPlan, font_path: str) -> np.ndarray:
    h, w = frame.shape[:2]
    for ev in plan.texts:
        alpha, scale = _event_alpha(t - ev.at_sec, ev.hold_sec)
        if alpha <= 0.01 or not ev.text:
            continue
        color, glow, size, y_frac = _STYLE[ev.kind]
        if ev.kind == "burst":
            scale *= 1.08
        if ev.kind == "title":
            sprite = text_sprite_3d(
                ev.text, size=size, color=color, depth_color=tuple(c // 3 for c in glow), glow=glow, font_path=font_path
            )
        else:
            sprite = text_sprite(ev.text, size=size, color=color, glow=glow, font_path=font_path)
        frame = composite(
            frame,
            sprite,
            cx=w / 2,
            cy=h * y_frac,
            alpha=alpha,
            scale=scale,
        )
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
        return _draw_texts(frame, t, plan, cfg.font_path)

    return clip.transform(transform)
