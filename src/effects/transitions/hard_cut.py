from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from moviepy import concatenate_videoclips

from src.effects.base import TransitionEffect
from src.effects.registry import register_transition


@register_transition("hard_cut")
@dataclass
class HardCutTransition(TransitionEffect):
    def apply(self, clip_a: Any, clip_b: Any, duration: float, *, offset: float | None = None) -> Any:
        return concatenate_videoclips([clip_a, clip_b], method="compose")
