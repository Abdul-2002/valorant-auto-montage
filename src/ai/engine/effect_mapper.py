from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from src.ai.schema import CreativeBrief, ScriptClipEffects
from src.config.models import ColorGradingEffectConfig, ShakeEffectConfig, VelocityEffectConfig, ZoomEffectConfig
from src.effects.presets.valorant import get_preset

# Per-clip treatment vocabulary. Uniform effects on every kill read as
# templated/AI-generated; real editors spend effects like a budget.
#   clean:     beat-retimed hard cut. No zoom, no shake, no slowmo.
#   punch:     zoom punch-in on the kill. No slowmo, no shake.
#   slow:      slowmo through the kill. No zoom, no shake.
#   cinematic: full treatment (slowmo + zoom + shake). Reserved for the best moments.
Recipe = Literal["clean", "punch", "slow", "cinematic"]

VALID_RECIPES: tuple[str, ...] = ("clean", "punch", "slow", "cinematic")

# At most this fraction of clips may zoom (punch + cinematic combined).
ZOOM_BUDGET_FRACTION: float = 0.4

# At most this many clips get the full cinematic treatment.
MAX_CINEMATIC: int = 3


@dataclass(frozen=True)
class EffectMappingInput:
    score: float
    arc_phase: str


def _intensity(*, creative_config: dict, brief: CreativeBrief | None) -> float:
    base = float(creative_config.get("effect_intensity", 0.7))
    if brief is not None and brief.intensity_bias is not None:
        return float(brief.intensity_bias)
    return base


def assign_recipes(
    *,
    scores: list[float],
    phases: list[str],
    directed: dict[int, str] | None = None,
) -> list[str]:
    """Assign a per-clip effect recipe with variety and an effect budget.

    ``directed`` holds AI-director (Gemini) choices per clip index; they are
    honored first, then the budget rules fill the rest deterministically.
    """
    n = len(scores)
    if n == 0:
        return []

    recipes: list[str | None] = [None] * n

    # 1. Director choices win (subject to the cinematic cap below).
    for i, r in (directed or {}).items():
        if 0 <= i < n and r in VALID_RECIPES:
            recipes[i] = r

    # 2. Highest-scored undirected kill gets cinematic if the cap allows.
    cine_used = sum(1 for r in recipes if r == "cinematic")
    if cine_used < MAX_CINEMATIC:
        best = max((i for i in range(n) if recipes[i] is None), key=lambda i: scores[i], default=None)
        if best is not None:
            recipes[best] = "cinematic"
            cine_used += 1

    # 3. Fill the rest by phase with alternation so no treatment repeats 3x.
    alt = 0
    for i in range(n):
        if recipes[i] is not None:
            continue
        phase = phases[i] if i < len(phases) else "build"
        if phase == "climax":
            recipes[i] = "punch" if alt % 2 == 0 else "slow"
        elif phase == "outro":
            recipes[i] = "slow"
        elif phase == "build":
            recipes[i] = "clean" if alt % 3 != 2 else "punch"
        else:  # intro
            recipes[i] = "clean"
        alt += 1

    # 4. Enforce cinematic cap and zoom budget (director choices included:
    # a budget the director can bypass is not a budget).
    final: list[str] = [str(r) for r in recipes]
    cine_idx = [i for i, r in enumerate(final) if r == "cinematic"]
    for i in sorted(cine_idx, key=lambda i: scores[i])[: max(0, len(cine_idx) - MAX_CINEMATIC)]:
        final[i] = "slow"

    zoom_budget = max(1, math.ceil(ZOOM_BUDGET_FRACTION * n))
    zoom_idx = [i for i, r in enumerate(final) if r in ("punch", "cinematic")]
    if len(zoom_idx) > zoom_budget:
        # Demote lowest-scored zooming clips first; cinematic survives longest.
        demotable = sorted(zoom_idx, key=lambda i: (final[i] == "cinematic", scores[i]))
        for i in demotable[: len(zoom_idx) - zoom_budget]:
            final[i] = "slow" if final[i] == "cinematic" else "clean"

    return final


def map_effects(
    *,
    inp: EffectMappingInput,
    creative_config: dict,
    brief: CreativeBrief | None,
    recipe: str = "cinematic",
) -> ScriptClipEffects:
    intensity = _intensity(creative_config=creative_config, brief=brief)
    preset = get_preset(str(inp.arc_phase), intensity)

    vel_keys = set(VelocityEffectConfig.model_fields) - {"enabled"}
    zoom_keys = set(ZoomEffectConfig.model_fields) - {"enabled"}
    shake_keys = set(ShakeEffectConfig.model_fields) - {"enabled"}
    color_keys = set(ColorGradingEffectConfig.model_fields) - {"enabled"}

    # Velocity is ALWAYS enabled: it performs the beat retiming that puts the
    # kill on the accent. Recipes only control whether it adds a slowmo dip.
    vel_params = {k: v for k, v in preset.velocity.items() if k in vel_keys}
    if recipe in ("clean", "punch"):
        vel_params["kill_slowmo_duration_sec"] = 0.0
    velocity = VelocityEffectConfig.model_validate({"enabled": True, **vel_params})

    zoom = None
    if recipe in ("punch", "cinematic"):
        zoom = ZoomEffectConfig.model_validate(
            {"enabled": True, **{k: v for k, v in preset.zoom.items() if k in zoom_keys}}
        )

    shake = None
    if recipe == "cinematic":
        shake = ShakeEffectConfig.model_validate(
            {"enabled": True, **{k: v for k, v in preset.shake.items() if k in shake_keys}}
        )

    color_grading = ColorGradingEffectConfig.model_validate(
        {"enabled": True, **{k: v for k, v in preset.color_grading.items() if k in color_keys}}
    )

    return ScriptClipEffects(
        velocity=velocity,
        zoom=zoom,
        shake=shake,
        color_grading=color_grading,
    )
