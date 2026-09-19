from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from moviepy import ColorClip, concatenate_videoclips

from src.effects.base import TransitionEffect
from src.effects.registry import register_transition


@register_transition("flash_black")
@dataclass
class FlashBlackTransition(TransitionEffect):
    flash_duration_sec: float = 0.05

    def apply(self, clip_a: Any, clip_b: Any, duration: float, *, offset: float | None = None) -> Any:
        w, h = clip_a.size
        d = float(self.flash_duration_sec) if self.flash_duration_sec is not None else float(duration)
        flash = ColorClip(size=(w, h), color=(0, 0, 0), duration=max(0.01, d))
        return concatenate_videoclips([clip_a, flash, clip_b], method="compose")
