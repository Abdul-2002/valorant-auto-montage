from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

from src.config.models import (
    CameraEffectConfig,
    ColorGradingEffectConfig,
    DeathPipEffectConfig,
    EdgeGlowEffectConfig,
    FreezeFrameEffectConfig,
    GhostFreezeEffectConfig,
    HighlightBloomEffectConfig,
    KillHitEffectConfig,
    LensDistortEffectConfig,
    PipInsetEffectConfig,
    LetterboxEffectConfig,
    LightWrapEffectConfig,
    MotionBlurEffectConfig,
    RgbSplitEffectConfig,
    ScopeVignetteEffectConfig,
    ShakeEffectConfig,
    VelocityEffectConfig,
    ZoomEffectConfig,
)


class NarrativePhase(BaseModel):
    duration_pct: int = Field(ge=5, le=60)
    pacing: Literal["slow", "medium", "fast", "accelerating", "decelerating"]
    intensity: float = Field(ge=0.0, le=1.0)


class ClipCuration(BaseModel):
    must_include: list[int] = Field(default_factory=list)
    prefer_exclude: list[int] = Field(default_factory=list)
    climax_candidates: list[int] = Field(default_factory=list)


class EffectBiases(BaseModel):
    slowmo_bias: float = Field(ge=0.0, le=1.0, default=0.5)
    flash_frequency: float = Field(ge=0.0, le=1.0, default=0.3)
    shake_intensity: float = Field(ge=0.0, le=1.0, default=0.5)
    zoom_aggression: float = Field(ge=0.0, le=1.0, default=0.5)
    color_warmth: float = Field(ge=0.0, le=1.0, default=0.5)


class SpecialTreatment(BaseModel):
    event_idx: int = Field(ge=0)
    note: str = ""
    treatment: str = ""
    hit_style: str = ""


def _coerce_pacing_field(val: Any) -> str:
    """Gemini often returns a float for pacing; map into allowed string literals."""
    allowed = ("slow", "medium", "fast", "accelerating", "decelerating")
    if isinstance(val, str) and val in allowed:
        return val
    if isinstance(val, (int, float)):
        x = float(val)
        if x < 0.22:
            return "slow"
        if x < 0.42:
            return "medium"
        if x < 0.62:
            return "fast"
        if x < 0.82:
            return "accelerating"
        return "decelerating"
    if isinstance(val, str):
        return "medium"
    return "medium"


class CreativeBrief(BaseModel):
    # Per-phase structure, or a single phase hint (e.g. "climax") for the whole edit.
    narrative_arc: Union[dict[str, NarrativePhase], str] = Field(default_factory=dict)
    clip_curation: ClipCuration = Field(default_factory=ClipCuration)
    effect_biases: EffectBiases = Field(default_factory=EffectBiases)
    transition_strategy: str = "beat_synced"
    special_treatments: list[SpecialTreatment] = Field(default_factory=list)
    reasoning: str = ""
    intensity_bias: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    effect_preferences: dict[str, Any] = Field(default_factory=dict)
    audio_cues: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _coerce_llm_narrative_arc(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        na = data.get("narrative_arc")
        if not isinstance(na, dict):
            return data
        fixed: dict[str, Any] = {}
        for phase_key, phase_val in na.items():
            if not isinstance(phase_val, dict):
                fixed[phase_key] = phase_val
                continue
            pv = dict(phase_val)
            if "pacing" in pv:
                pv["pacing"] = _coerce_pacing_field(pv.get("pacing"))
            if "duration_pct" in pv and isinstance(pv["duration_pct"], float):
                pv["duration_pct"] = int(round(pv["duration_pct"]))
            if "intensity" in pv and isinstance(pv["intensity"], str):
                try:
                    pv["intensity"] = float(pv["intensity"])
                except ValueError:
                    pv["intensity"] = 0.5
            fixed[phase_key] = pv
        out = dict(data)
        out["narrative_arc"] = fixed
        return out


class ScriptTransition(BaseModel):
    type: str = "hard_cut"
    duration_sec: float = Field(gt=0.0, lt=2.0, default=0.15)


class ScriptClipEffects(BaseModel):
    velocity: Optional[VelocityEffectConfig] = None
    camera: Optional[CameraEffectConfig] = None
    ghost_freeze: Optional[GhostFreezeEffectConfig] = None
    pip_inset: Optional[PipInsetEffectConfig] = None
    zoom: Optional[ZoomEffectConfig] = None
    shake: Optional[ShakeEffectConfig] = None
    color_grading: Optional[ColorGradingEffectConfig] = None
    scope_vignette: Optional[ScopeVignetteEffectConfig] = None
    death_pip: Optional[DeathPipEffectConfig] = None
    edge_glow: Optional[EdgeGlowEffectConfig] = None
    kill_hit: Optional[KillHitEffectConfig] = None
    freeze_frame: Optional[FreezeFrameEffectConfig] = None
    motion_blur: Optional[MotionBlurEffectConfig] = None
    letterbox: Optional[LetterboxEffectConfig] = None
    lens_distort: Optional[LensDistortEffectConfig] = None
    rgb_split: Optional[RgbSplitEffectConfig] = None
    highlight_bloom: Optional[HighlightBloomEffectConfig] = None
    light_wrap: Optional[LightWrapEffectConfig] = None


class ScriptClip(BaseModel):
    video_index: int
    start_sec: float = Field(ge=0.0)
    end_sec: float = Field(gt=0.0)
    kill_timestamp_sec: float = Field(ge=0.0)
    score: float = Field(ge=0.0, le=1.0)
    # Output-timeline placement (in music time). These fields enable beat-synced cuts by
    # ensuring clip boundaries align to BeatMap times, independent from source timestamps.
    output_start_sec: Optional[float] = Field(default=None, ge=0.0)
    output_end_sec: Optional[float] = Field(default=None, gt=0.0)
    # Uniform speed for scripts without time_knots (hand-written / legacy scripts).
    # >1.0 => faster playback (shorter), <1.0 => slower playback (longer).
    speed_factor: Optional[float] = Field(default=None, gt=0.0, le=10.0)
    # Every kill in the clip (multi-kill bursts), absolute source seconds.
    kill_timestamps_sec: list[float] = Field(default_factory=list)
    # Kill times relative to output_start_sec; each lands on a beat.
    kill_output_times_sec: list[float] = Field(default_factory=list)
    # Retime curve: (output_sec, source_sec) pairs relative to clip start.
    time_knots: Optional[list[tuple[float, float]]] = None
    recipe: str = "clean"
    hit_style: str = "flash_blur"
    scoped: bool = False
    # Strong beats inside the clip (relative to output_start_sec) for camera pulses.
    accent_beats_sec: list[float] = Field(default_factory=list)
    pip_style: str = ""
    ghost_candidate: bool = False
    effects: ScriptClipEffects = Field(default_factory=ScriptClipEffects)
    transition_to_next: Optional[ScriptTransition] = None
    arc_phase: Literal["intro", "build", "climax", "outro"] = "build"


class MontageScript(BaseModel):
    clips: list[ScriptClip] = Field(min_length=1)
    creative_config_resolved: dict[str, Any] = Field(default_factory=dict)
    brief: Optional[CreativeBrief] = None
    reasoning: str = ""
