from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from moviepy import concatenate_videoclips

from src.effects.base import TransitionEffect
from src.effects.registry import register_transition


@register_transition("whip_pan")
@dataclass
class WhipPanTransition(TransitionEffect):
    blur_amount: int = 35
    duration_sec: float = 0.15

    def apply(self, clip_a: Any, clip_b: Any, duration: float, *, offset: float | None = None) -> Any:
        # Minimal v1 placeholder: treat as hard cut; later replace with directional blur tween.
        return concatenate_videoclips([clip_a, clip_b], method="compose")
