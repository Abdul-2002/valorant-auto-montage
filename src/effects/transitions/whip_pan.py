from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from moviepy import concatenate_videoclips

from src.effects.base import TransitionEffect
from src.effects.registry import register_transition


@register_transition("whip_pan")
@dataclass
class WhipPanTransition(TransitionEffect):
    """Placeholder registration; assembler applies duration-preserving whip styling."""

    blur_amount: int = 35
    duration_sec: float = 0.14

    def apply(self, clip_a: Any, clip_b: Any, duration: float, *, offset: float | None = None) -> Any:
        # Assembler owns the real duration-preserving whip. This path is a safe fallback.
        return concatenate_videoclips([clip_a, clip_b], method="compose")


@register_transition("push")
@dataclass
class PushTransition(TransitionEffect):
    duration_sec: float = 0.12

    def apply(self, clip_a: Any, clip_b: Any, duration: float, *, offset: float | None = None) -> Any:
        return concatenate_videoclips([clip_a, clip_b], method="compose")
