from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from src.ai.schema import CreativeBrief, ScriptClipEffects
from src.config.models import (
    ColorGradingEffectConfig,
    FreezeFrameEffectConfig,
    HighlightBloomEffectConfig,
    ImpactStylizeEffectConfig,
    LetterboxEffectConfig,
    LightWrapEffectConfig,
    MotionBlurEffectConfig,
    RgbSplitEffectConfig,
    ScopeVignetteEffectConfig,
    ShakeEffectConfig,
    VelocityEffectConfig,
    ZoomEffectConfig,
)
from src.effects.presets.valorant import get_preset

# Per-clip treatment vocabulary. Uniform effects on every kill read as
# templated/AI-generated; real editors spend effects like a budget.
#   clean:     beat-retimed hard cut. No zoom, no shake, no slowmo.
#   punch:     zoom punch-in on the kill. No slowmo, no shake.
#   slow:      slowmo through the kill. No zoom, no shake.
#   cinematic: full Zeeshu treatment (slowmo + overlays). Cap 2-3 clips.
Recipe = Literal["clean", "punch", "slow", "cinematic"]

VALID_RECIPES: tuple[str, ...] = ("clean", "punch", "slow", "cinematic")

ZOOM_BUDGET_FRACTION: float = 0.4
# Heavy overlays (scope/PiP/stylize/etc.) only on cinematic clips.
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
    """Assign recipes with a hard cinematic overlay budget of 2–3 clips."""
    n = len(scores)
    if n == 0:
        return []

    recipes: list[str | None] = [None] * n
    for i, r in (directed or {}).items():
        if 0 <= i < n and r in VALID_RECIPES:
            recipes[i] = r

    # Rank undirected clips: climax phase first, then score.
    undirected = [i for i in range(n) if recipes[i] is None]
    undirected.sort(
        key=lambda i: (
            1 if (phases[i] if i < len(phases) else "") == "climax" else 0,
            scores[i],
        ),
        reverse=True,
    )

    cine_count = sum(1 for r in recipes if r == "cinematic")
    target_cine = min(MAX_CINEMATIC, max(2, min(3, n // 4 + 1)) if n >= 4 else min(MAX_CINEMATIC, n))
    for i in undirected:
        if cine_count >= target_cine:
            break
        recipes[i] = "cinematic"
        cine_count += 1

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
        else:
            recipes[i] = "clean"
        alt += 1

    final: list[str] = [str(r) for r in recipes]
    cine_idx = [i for i, r in enumerate(final) if r == "cinematic"]
    if len(cine_idx) > MAX_CINEMATIC:
        for i in sorted(cine_idx, key=lambda i: scores[i])[: len(cine_idx) - MAX_CINEMATIC]:
            final[i] = "slow"

    zoom_budget = max(1, math.ceil(ZOOM_BUDGET_FRACTION * n))
    zoom_idx = [i for i, r in enumerate(final) if r in ("punch", "cinematic")]
    if len(zoom_idx) > zoom_budget:
        demotable = sorted(zoom_idx, key=lambda i: (final[i] == "cinematic", scores[i]))
        for i in demotable[: len(zoom_idx) - zoom_budget]:
            if final[i] == "cinematic":
                # Never demote cinematic below MAX — demote punch instead when possible.
                continue
            final[i] = "clean"
        zoom_idx = [i for i, r in enumerate(final) if r in ("punch", "cinematic")]
        if len(zoom_idx) > zoom_budget:
            demotable = sorted(
                [i for i in zoom_idx if final[i] != "cinematic"],
                key=lambda i: scores[i],
            )
            for i in demotable[: max(0, len(zoom_idx) - zoom_budget)]:
                final[i] = "clean"

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

    vel_params = {k: v for k, v in preset.velocity.items() if k in vel_keys}
    if recipe in ("clean", "punch"):
        vel_params["kill_slowmo_duration_sec"] = 0.0
    velocity = VelocityEffectConfig.model_validate({"enabled": True, **vel_params})

    zoom = None
    if recipe in ("punch", "cinematic"):
        zparams = {k: v for k, v in preset.zoom.items() if k in zoom_keys}
        if recipe == "cinematic":
            zparams.setdefault("max_zoom", 1.35)
            zparams.setdefault("duration_sec", 0.5)
            zparams.setdefault("crash_in_frac", 0.35)
        zoom = ZoomEffectConfig.model_validate({"enabled": True, **zparams})

    shake = None
    if recipe == "cinematic":
        shake = ShakeEffectConfig.model_validate(
            {"enabled": True, **{k: v for k, v in preset.shake.items() if k in shake_keys}}
        )

    color_grading = ColorGradingEffectConfig.model_validate(
        {"enabled": True, **{k: v for k, v in preset.color_grading.items() if k in color_keys}}
    )

    # Heavy Zeeshu overlays: cinematic only (budget 2-3 clips).
    heavy = recipe == "cinematic"
    return ScriptClipEffects(
        velocity=velocity,
        zoom=zoom,
        shake=shake,
        color_grading=color_grading,
        scope_vignette=ScopeVignetteEffectConfig(enabled=heavy) if heavy else None,
        # Same-frame corner inset duplicates the kill. Zishu stays first-person.
        death_pip=None,
        impact_stylize=ImpactStylizeEffectConfig(enabled=heavy) if heavy else None,
        freeze_frame=FreezeFrameEffectConfig(enabled=heavy) if heavy else None,
        motion_blur=MotionBlurEffectConfig(enabled=heavy) if heavy else None,
        letterbox=LetterboxEffectConfig(enabled=heavy) if heavy else None,
        # Reflect border mirrors HUD and any overlay. Not part of the first-person look.
        lens_distort=None,
        rgb_split=RgbSplitEffectConfig(enabled=heavy) if heavy else None,
        highlight_bloom=HighlightBloomEffectConfig(enabled=heavy) if heavy else None,
        light_wrap=LightWrapEffectConfig(enabled=heavy) if heavy else None,
    )
