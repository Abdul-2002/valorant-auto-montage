"""Time envelopes (0..1) for kill-anchored effects, in output seconds."""

from __future__ import annotations


def decay_envelope(t: float, anchor: float, decay_sec: float) -> float:
    """0 before the kill frame, 1 on it, ease-out to 0 over ``decay_sec`` (flash/blur keyframes)."""
    if t < anchor or decay_sec <= 0.0:
        return 0.0
    u = (t - anchor) / decay_sec
    if u >= 1.0:
        return 0.0
    return (1.0 - u) ** 2


def hold_fade_envelope(t: float, anchor: float, hold_sec: float, fade_sec: float) -> float:
    """Full strength from the kill for ``hold_sec``, then linear blend back to the original."""
    if t < anchor:
        return 0.0
    rel = t - anchor
    if rel <= hold_sec:
        return 1.0
    if fade_sec <= 0.0:
        return 0.0
    return max(0.0, 1.0 - (rel - hold_sec) / fade_sec)
