from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import cv2
import numpy as np
from moviepy.video.VideoClip import VideoClip

from src.effects.base import ClipEffect, EffectContext
from src.effects.envelopes import decay_envelope
from src.effects.registry import register_clip_effect

CAMERA_TRANSITIONS: tuple[str, ...] = ("zoom_in", "spin")
_TRANSITION_ZOOM = 0.3
_SPIN_ZOOM = 0.25
_SPIN_DEG = 8.0
_REFERENCE_HEIGHT = 1080.0


@dataclass(frozen=True)
class CameraState:
    scale: float = 1.0
    rot_deg: float = 0.0
    dx: float = 0.0
    dy: float = 0.0
    blur: float = 0.0  # 0..1 zoom-blur amount during transitions


def _jitter(i: int, axis: int, seed: float) -> float:
    x = (int(seed * 1000) * 2654435761 ^ (i + 1) * 1103515245 ^ axis * 12345) & 0xFFFFFFFF
    x = (x * 1664525 + 1013904223) & 0xFFFFFFFF
    return (x / 2**32) * 2.0 - 1.0


def _smoothstep(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return u * u * (3.0 - 2.0 * u)


def _crash(t: float, kill: float, amount: float, dur: float) -> float:
    """Ease-in crash toward the kill (78% of the window), fast snap back after it."""
    rise, fall = dur * 0.78, dur * 0.22
    if kill - rise <= t < kill:
        return amount * ((t - (kill - rise)) / rise) ** 3
    if kill <= t < kill + fall:
        return amount * (1.0 - (t - kill) / fall) ** 2
    return 0.0


def _transition(t: float, clip_dur: float, head: str, tail: str, dur: float) -> tuple[float, float, float]:
    """(scale add, rotation deg, blur) for zoom-through / spin transitions at clip edges."""
    if head in CAMERA_TRANSITIONS and t < dur:
        e = (1.0 - t / dur) ** 2
        return (_TRANSITION_ZOOM * e, 0.0, e) if head == "zoom_in" else (_SPIN_ZOOM * e, _SPIN_DEG * e, e)
    if tail in CAMERA_TRANSITIONS and t > clip_dur - dur:
        e = ((t - (clip_dur - dur)) / dur) ** 2
        return (_TRANSITION_ZOOM * e, 0.0, e) if tail == "zoom_in" else (_SPIN_ZOOM * e, -_SPIN_DEG * e, e)
    return 0.0, 0.0, 0.0


def _cover_scale(rot_deg: float, shift_px: float, w: int, h: int) -> float:
    """Smallest zoom that keeps a rotated, shifted frame free of empty borders."""
    th = math.radians(abs(rot_deg))
    return math.cos(th) + (max(w, h) / min(w, h)) * math.sin(th) + 2.0 * shift_px / min(w, h)


@register_clip_effect("camera")
@dataclass
class CameraEffect(ClipEffect):
    """Virtual camera: one affine warp per frame so the POV never sits still on a beat."""

    enabled: bool = True
    kill_shake_px: float = 8.0
    kill_shake_rot_deg: float = 0.6
    kill_shake_sec: float = 0.28
    beat_pulse: float = 0.03
    beat_pulse_sec: float = 0.18
    push_in: float = 0.0
    crash_zoom: float = 0.0
    crash_zoom_sec: float = 0.3
    transition_sec: float = 0.14

    def state_at(
        self,
        t: float,
        *,
        kills: Sequence[float],
        beats: Sequence[float],
        slow_window: tuple[float, float] | None,
        clip_dur: float,
        head: str,
        tail: str,
        fps: int,
        scale_px: float = 1.0,
    ) -> CameraState:
        scale = 1.0 + sum(self.beat_pulse * decay_envelope(t, b, self.beat_pulse_sec) for b in beats)
        if kills and self.crash_zoom > 0.0:
            scale += _crash(t, kills[-1], self.crash_zoom, self.crash_zoom_sec)
        if slow_window is not None and self.push_in > 0.0 and t >= slow_window[0]:
            a, b = slow_window
            scale += self.push_in * _smoothstep((t - a) / max(1e-6, b - a))
        dx = dy = rot = 0.0
        for k in kills:
            e = decay_envelope(t, k, self.kill_shake_sec)
            if e > 0.0:
                i = int((t - k) * fps)
                dx += self.kill_shake_px * scale_px * e * _jitter(i, 0, k)
                dy += self.kill_shake_px * scale_px * e * _jitter(i, 1, k)
                rot += self.kill_shake_rot_deg * e * _jitter(i, 2, k)
        t_scale, t_rot, blur = _transition(t, clip_dur, head, tail, self.transition_sec)
        return CameraState(scale=scale + t_scale, rot_deg=rot + t_rot, dx=dx, dy=dy, blur=blur)

    def apply(self, ctx: EffectContext) -> Any:
        clip: VideoClip = ctx.clip
        if not self.enabled:
            return clip
        cfg = ctx.config
        kills = tuple(float(k) for k in ctx.kill_timestamps)
        beats = tuple(float(b) for b in cfg.get("_accent_beats", ()) or ())
        window = cfg.get("_slowmo_window")
        slow_window = (float(window[0]), float(window[1])) if window else None
        clip_dur = float(getattr(clip, "duration", None) or ctx.clip_duration)
        head, tail = str(cfg.get("_transition_in", "")), str(cfg.get("_transition_out", ""))
        fps = max(1, int(ctx.fps))

        def transform(get_frame, t: float):
            frame = get_frame(t)
            h, w = frame.shape[:2]
            s = self.state_at(
                float(t), kills=kills, beats=beats, slow_window=slow_window, clip_dur=clip_dur,
                head=head, tail=tail, fps=fps, scale_px=h / _REFERENCE_HEIGHT,
            )
            if abs(s.scale - 1.0) < 1e-3 and abs(s.rot_deg) < 1e-3 and abs(s.dx) < 0.3 and abs(s.dy) < 0.3:
                return frame
            return warp_frame(frame, s)

        return clip.transform(transform)


def _affine(state: CameraState, w: int, h: int, scale: float) -> np.ndarray:
    m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), state.rot_deg, scale)
    m[0, 2] += state.dx
    m[1, 2] += state.dy
    return m


def warp_frame(frame: np.ndarray, state: CameraState) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = max(state.scale, _cover_scale(state.rot_deg, max(abs(state.dx), abs(state.dy)), w, h))
    out = cv2.warpAffine(frame, _affine(state, w, h, scale), (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    if state.blur < 0.05:
        return out
    acc = out.astype(np.float32)
    for k in (1, 2):
        m = _affine(state, w, h, scale * (1.0 + 0.035 * k * state.blur))
        acc += cv2.warpAffine(frame, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    return (acc / 3.0).astype(np.uint8)
