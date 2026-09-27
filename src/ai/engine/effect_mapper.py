from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from src.ai.schema import CreativeBrief, ScriptClipEffects
from src.ai.engine.feature_budget import PIP_STYLES
from src.config.models import (
    CameraEffectConfig,
    ColorGradingEffectConfig,
    EdgeGlowEffectConfig,
    KillHitEffectConfig,
    PipInsetEffectConfig,
    ScopeVignetteEffectConfig,
    VelocityEffectConfig,
)
from src.effects.presets.valorant import get_preset

# Per-clip treatment vocabulary. Every recipe hits the kill frame on the beat
# (flash + lens blur, glow, or flash + shake); recipes differ in what follows.
#   clean:     kill hit only.
#   punch:     kill hit + crash zoom. No slow-mo.
#   slow:      kill hit + post-kill slow-mo (Zishu signature). The default.
#   cinematic: hit + post-kill slow-mo + camera push/crash + edge-glow. Budgeted.
Recipe = Literal["clean", "punch", "slow", "cinematic"]
VALID_RECIPES: tuple[str, ...] = ("clean", "punch", "slow", "cinematic")
HIT_STYLE_CYCLE: tuple[str, ...] = ("flash_blur", "flash_blur", "glow", "flash_shake")

ZOOM_BUDGET_FRACTION: float = 0.45
MAX_CINEMATIC: int = 2
_PHASE_ROTATION: dict[str, tuple[str, ...]] = {
    "intro": ("clean", "slow"),
    "build": ("slow", "punch", "slow", "punch"),
    "climax": ("punch", "slow"),
    "outro": ("slow",),
}
# Output seconds of post-kill slow-mo and its speed, per recipe.
_SLOWMO_OUT_SEC: dict[str, float] = {"slow": 0.9, "cinematic": 1.2}
_SLOWMO_FACTOR_CLIMAX: float = 0.4
_SLOWMO_FACTOR_DEFAULT: float = 0.45


@dataclass(frozen=True)
class EffectMappingInput:
    score: float
    arc_phase: str


def _intensity(*, creative_config: dict, brief: CreativeBrief | None) -> float:
    if brief is not None and brief.intensity_bias is not None:
        return float(brief.intensity_bias)
    return float(creative_config.get("effect_intensity", 0.7))


def _pick_cinematic(scores: list[float], phases: list[str], recipes: list[str | None]) -> None:
    n = len(scores)
    target = min(MAX_CINEMATIC, max(1, n // 4)) if n >= 2 else 0
    have = sum(1 for r in recipes if r == "cinematic")
    ranked = sorted(
        (i for i in range(n) if recipes[i] is None),
        key=lambda i: (phases[i] == "climax", scores[i]),
        reverse=True,
    )
    for i in ranked[: max(0, target - have)]:
        recipes[i] = "cinematic"


def _enforce_budgets(final: list[str], scores: list[float]) -> None:
    cine = sorted((i for i, r in enumerate(final) if r == "cinematic"), key=lambda i: scores[i])
    for i in cine[: max(0, len(cine) - MAX_CINEMATIC)]:
        final[i] = "slow"
    budget = max(1, math.ceil(ZOOM_BUDGET_FRACTION * len(final)))
    punches = sorted((i for i, r in enumerate(final) if r == "punch"), key=lambda i: scores[i])
    excess = sum(1 for r in final if r in ("punch", "cinematic")) - budget
    for i in punches[: max(0, excess)]:
        final[i] = "slow"


def assign_recipes(
    *,
    scores: list[float],
    phases: list[str],
    directed: dict[int, str] | None = None,
) -> list[str]:
    """Director choices first, then budgeted phase rotation (slow-mo is the default)."""
    n = len(scores)
    if n == 0:
        return []
    phases = [phases[i] if i < len(phases) else "build" for i in range(n)]
    recipes: list[str | None] = [None] * n
    for i, r in (directed or {}).items():
        if 0 <= i < n and r in VALID_RECIPES:
            recipes[i] = r
    _pick_cinematic(scores, phases, recipes)
    counters: dict[str, int] = {}
    for i in range(n):
        if recipes[i] is not None:
            continue
        rotation = _PHASE_ROTATION.get(phases[i], _PHASE_ROTATION["build"])
        k = counters.get(phases[i], 0)
        recipes[i] = rotation[k % len(rotation)]
        counters[phases[i]] = k + 1
    final = [str(r) for r in recipes]
    _enforce_budgets(final, scores)
    return final


def assign_hit_styles(*, n: int, directed: dict[int, str] | None = None) -> list[str]:
    """Director-chosen hit styles, else a varied rotation (same hit on every kill reads as a template)."""
    styles = [HIT_STYLE_CYCLE[i % len(HIT_STYLE_CYCLE)] for i in range(n)]
    for i, s in (directed or {}).items():
        if 0 <= i < n and s in HIT_STYLE_CYCLE:
            styles[i] = s
    return styles


def slowmo_params(*, recipe: str, arc_phase: str) -> tuple[float, float]:
    """(post-kill slow-mo output seconds, speed factor) before the source-fps cap."""
    duration = _SLOWMO_OUT_SEC.get(recipe, 0.0)
    climactic = recipe == "cinematic" or arc_phase == "climax"
    return duration, (_SLOWMO_FACTOR_CLIMAX if climactic else _SLOWMO_FACTOR_DEFAULT)


def _camera_for(recipe: str) -> CameraEffectConfig:
    """Camera on every clip. Punch crashes in; slow/cinematic push in after the kill."""
    if recipe == "punch":
        return CameraEffectConfig(enabled=True, crash_zoom=0.22, crash_zoom_sec=0.30, push_in=0.0, beat_pulse=0.04, kill_shake_px=10.0)
    if recipe == "cinematic":
        return CameraEffectConfig(enabled=True, crash_zoom=0.12, crash_zoom_sec=0.34, push_in=0.14, beat_pulse=0.04, kill_shake_px=12.0)
    if recipe == "slow":
        return CameraEffectConfig(enabled=True, crash_zoom=0.0, push_in=0.10, beat_pulse=0.03, kill_shake_px=8.0)
    return CameraEffectConfig(enabled=True, crash_zoom=0.0, push_in=0.0, beat_pulse=0.02, kill_shake_px=6.0)


def _pip_for(pip_style: str) -> PipInsetEffectConfig | None:
    if pip_style not in PIP_STYLES:
        return None
    return PipInsetEffectConfig(enabled=True, style=pip_style)  # type: ignore[arg-type]


def map_effects(
    *,
    inp: EffectMappingInput,
    creative_config: dict,
    brief: CreativeBrief | None,
    recipe: str = "slow",
    hit_style: str = "flash_blur",
    scoped: bool = False,
    slowmo_factor: float | None = None,
    pip_style: str = "",
) -> ScriptClipEffects:
    intensity = _intensity(creative_config=creative_config, brief=brief)
    preset = get_preset(str(inp.arc_phase), intensity)
    slow_sec, default_factor = slowmo_params(recipe=recipe, arc_phase=str(inp.arc_phase))
    velocity = VelocityEffectConfig(
        enabled=True,
        kill_slowmo_duration_sec=slow_sec,
        kill_slowmo_factor=float(slowmo_factor if slowmo_factor is not None else default_factor),
    )
    color_keys = set(ColorGradingEffectConfig.model_fields) - {"enabled"}
    # ~AE Brightness +100 at intensity 0.85 (Zishu kill flash), scaled by style intensity.
    flash = min(0.5, max(0.2, 0.2 + 0.25 * intensity))
    return ScriptClipEffects(
        velocity=velocity,
        camera=_camera_for(recipe),
        pip_inset=_pip_for(pip_style),
        color_grading=ColorGradingEffectConfig.model_validate(
            {"enabled": True, **{k: v for k, v in preset.color_grading.items() if k in color_keys}}
        ),
        kill_hit=KillHitEffectConfig(enabled=True, style=hit_style, flash_strength=flash),
        edge_glow=EdgeGlowEffectConfig(enabled=True) if recipe == "cinematic" else None,
        scope_vignette=ScopeVignetteEffectConfig(enabled=True) if scoped else None,
    )
