from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from moviepy import CompositeVideoClip, concatenate_videoclips

from src.effects.base import TransitionEffect
from src.effects.registry import register_transition


@dataclass
class _CrossfadeLikeTransition(TransitionEffect):
    """MoviePy fallback for xfade-style transitions.

    v1 uses MoviePy composition (crossfade) so the system works without complex
    ffmpeg filtergraphs. A future iteration can replace this with real ffmpeg
    xfade filter_complex rendering.
    """

    xfade_duration_sec: float = 0.2

    def apply(self, clip_a: Any, clip_b: Any, duration: float, *, offset: float | None = None) -> Any:
        d = max(0.0, float(duration or self.xfade_duration_sec))
        if d <= 0:
            return concatenate_videoclips([clip_a, clip_b], method="compose")

        # Best-effort MoviePy crossfade that works in both v1/v2.
        # If crossfade methods aren't available, fall back to concat.
        try:
            a_dur = float(getattr(clip_a, "duration", None) or 0.0)
            start_b = max(0.0, a_dur - d)

            # set_start -> with_start (MoviePy v2)
            if hasattr(clip_b, "set_start"):
                b = clip_b.set_start(start_b)  # type: ignore[attr-defined]
            else:
                b = clip_b.with_start(start_b)  # type: ignore[attr-defined]

            # crossfadein exists in MoviePy v1; v2 uses effect classes but keeps crossfadein for compatibility.
            if hasattr(b, "crossfadein"):
                b = b.crossfadein(d)  # type: ignore[attr-defined]

            comp = CompositeVideoClip([clip_a, b])
            total = max(0.0, a_dur) + float(getattr(clip_b, "duration", 0.0) or 0.0) - d
            if hasattr(comp, "set_duration"):
                comp = comp.set_duration(total)  # type: ignore[attr-defined]
            else:
                comp = comp.with_duration(total)  # type: ignore[attr-defined]
            return comp
        except Exception:
            return concatenate_videoclips([clip_a, clip_b], method="compose")


# Register a useful subset of names (extensible by adding more here).
for _name in [
    "fade",
    "dissolve",
    "wipeleft",
    "wiperight",
    "wipeup",
    "wipedown",
    "slideleft",
    "slideright",
    "slideup",
    "slidedown",
    "zoomin",
    "circlecrop",
    "circleopen",
    "circleclose",
    "radial",
    "pixelize",
    "fadeblack",
    "fadewhite",
    "fadegrays",
    "diagtl",
    "diagtr",
    "diagbl",
    "diagbr",
    "horzopen",
    "horzclose",
    "vertopen",
    "vertclose",
    "coverleft",
    "coverright",
    "revealleft",
    "revealright",
    "distance",
]:

    register_transition(_name)(type(f"Xfade_{_name}", (_CrossfadeLikeTransition,), {}))
