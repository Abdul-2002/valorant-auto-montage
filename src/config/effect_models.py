"""Per-clip effect configuration models (split from models.py to keep modules small)."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class VelocityEffectConfig(BaseModel):
    enabled: bool = True
    # Post-kill slow-mo (Zishu style): speed right after the last kill of a clip.
    kill_slowmo_factor: float = Field(gt=0.05, lt=1.0, default=0.4)
    # Output seconds of post-kill slow-mo. 0.0 disables it (clean/punch recipes).
    kill_slowmo_duration_sec: float = Field(ge=0.0, lt=5.0, default=0.9)
    # Slow-mo never drops below this many distinct source frames per second
    # (no frame interpolation: 60fps sources cap at 0.5x, 120fps at 0.25x).
    slowmo_min_unique_fps: float = Field(ge=10.0, le=120.0, default=30.0)
    approach_speed: float = Field(ge=0.5, le=2.0, default=1.15)
    exit_speed: float = Field(ge=0.5, le=2.5, default=1.35)
    transition_speedup_factor: float = Field(gt=0.25, lt=10.0, default=2.0)
    easing: str = Field(default="ease_in_out_cubic")


class CameraEffectConfig(BaseModel):
    """Virtual camera: kill shakes, beat zoom pulses, slow-mo push-in, crash zoom, zoom/spin transitions."""

    enabled: bool = True
    kill_shake_px: float = Field(ge=0.0, le=60.0, default=8.0)
    kill_shake_rot_deg: float = Field(ge=0.0, le=5.0, default=0.6)
    kill_shake_sec: float = Field(gt=0.02, le=1.0, default=0.28)
    beat_pulse: float = Field(ge=0.0, le=0.2, default=0.03)
    beat_pulse_sec: float = Field(gt=0.02, le=1.0, default=0.18)
    push_in: float = Field(ge=0.0, le=0.3, default=0.0)
    crash_zoom: float = Field(ge=0.0, le=1.0, default=0.0)
    crash_zoom_sec: float = Field(gt=0.05, le=1.5, default=0.3)
    transition_sec: float = Field(gt=0.05, le=0.6, default=0.14)


class ZoomEffectConfig(BaseModel):
    enabled: bool = True
    max_zoom: float = Field(ge=1.0, le=3.0, default=1.25)
    duration_sec: float = Field(gt=0.01, lt=5.0, default=0.3)
    # Fraction of the zoom window spent crashing IN (rest settles/zooms out).
    crash_in_frac: float = Field(ge=0.15, le=0.85, default=0.35)
    easing: str = Field(default="ease_out_quad")
    center: Literal["screen_center", "kill_position"] = "screen_center"


class ShakeEffectConfig(BaseModel):
    enabled: bool = True
    amplitude_px: int = Field(ge=0, le=50, default=6)
    decay_rate: float = Field(gt=0.0, lt=1.0, default=0.85)
    duration_frames: int = Field(ge=0, le=120, default=8)


class ColorGradingEffectConfig(BaseModel):
    enabled: bool = True
    saturation: float = Field(gt=0.0, le=3.0, default=1.3)
    contrast: float = Field(gt=0.0, le=3.0, default=1.1)
    brightness: float = Field(ge=-1.0, le=1.0, default=0.02)


class ScopeVignetteEffectConfig(BaseModel):
    """Sniper-kill scope mask; the composer enables it only for scoped kills."""

    enabled: bool = False
    pre_sec: float = Field(gt=0.05, lt=2.0, default=0.35)
    release_sec: float = Field(gt=0.02, lt=1.0, default=0.12)
    # Closed-ring radius in half-screen-height units (1.0 touches top/bottom edges).
    inner_radius: float = Field(ge=0.3, le=1.5, default=0.92)
    darkness: float = Field(ge=0.0, le=1.0, default=0.92)
    feather: float = Field(gt=0.0, le=0.5, default=0.05)


class KillHitEffectConfig(BaseModel):
    """Per-kill hit on the beat. flash_blur = brightness + lens blur decaying (Zishu)."""

    enabled: bool = True
    style: Literal["flash_blur", "glow", "flash_shake"] = "flash_blur"
    decay_sec: float = Field(gt=0.05, lt=1.5, default=0.3)
    flash_strength: float = Field(ge=0.0, le=1.0, default=0.5)
    blur_px: float = Field(ge=0.0, le=64.0, default=16.0)
    glow_threshold: float = Field(ge=0.2, le=0.95, default=0.55)
    glow_blur_px: int = Field(ge=3, le=151, default=31)
    glow_intensity: float = Field(ge=0.0, le=3.0, default=1.2)
    # Strength of earlier kills in a multi-kill clip relative to the last one.
    minor_scale: float = Field(ge=0.0, le=1.0, default=0.6)


class EdgeGlowEffectConfig(BaseModel):
    """Zishu find-edges + single-hue tritone + glow, blended back out after the kill."""

    enabled: bool = False
    hold_sec: float = Field(ge=0.0, lt=1.0, default=0.1)
    fade_sec: float = Field(gt=0.05, lt=2.0, default=0.5)
    mid_rgb: tuple[int, int, int] = (40, 140, 255)
    highlight_rgb: tuple[int, int, int] = (210, 240, 255)
    glow_threshold: float = Field(ge=0.0, le=0.95, default=0.3)
    glow_blur_px: int = Field(ge=3, le=151, default=51)
    glow_intensity: float = Field(ge=0.0, le=3.0, default=1.0)


class GhostFreezeEffectConfig(BaseModel):
    """Ghosted rotoscope freeze-frame: the enemy cut from the kill frame fades in before the kill."""

    enabled: bool = False
    cutout_path: Optional[str] = None
    # Top-left of the cut-out in output-frame pixels (where the enemy stood on the kill frame).
    anchor_x: int = Field(ge=0, default=0)
    anchor_y: int = Field(ge=0, default=0)
    lead_sec: float = Field(gt=0.1, le=2.0, default=0.5)
    max_alpha: float = Field(ge=0.1, le=1.0, default=0.55)
    outline_rgb: tuple[int, int, int] = (170, 230, 255)


class PipInsetEffectConfig(BaseModel):
    """Picture-in-picture card after the kill: frozen zoom of the kill or a slow-mo replay."""

    enabled: bool = False
    style: Literal["freeze_inset", "replay_inset"] = "freeze_inset"
    delay_sec: float = Field(ge=0.0, le=1.0, default=0.08)
    hold_sec: float = Field(gt=0.2, le=3.0, default=1.0)
    zoom: float = Field(ge=1.0, le=4.0, default=2.2)
    replay_window_sec: float = Field(gt=0.1, le=2.0, default=0.6)
    replay_speed: float = Field(gt=0.1, le=1.0, default=0.5)
    # Card width in pixels at 1080p; must stay inside the 9:16 center crop (608 px).
    width_px: int = Field(ge=160, le=600, default=520)


class DeathPipEffectConfig(BaseModel):
    enabled: bool = False
    duration_sec: float = Field(gt=0.1, lt=2.5, default=0.95)
    scale: float = Field(ge=1.2, le=4.0, default=2.6)
    size_frac: float = Field(ge=0.15, le=0.5, default=0.36)
    margin_frac: float = Field(ge=0.01, le=0.1, default=0.025)
    border_px: int = Field(ge=0, le=16, default=5)
    desaturate: float = Field(ge=0.0, le=1.0, default=0.45)


class FreezeFrameEffectConfig(BaseModel):
    enabled: bool = False
    duration_sec: float = Field(gt=0.02, lt=0.5, default=0.08)


class MotionBlurEffectConfig(BaseModel):
    enabled: bool = False
    duration_sec: float = Field(gt=0.05, lt=1.5, default=0.25)
    amount_px: int = Field(ge=1, le=80, default=28)


class LetterboxEffectConfig(BaseModel):
    enabled: bool = False
    bar_frac: float = Field(ge=0.02, le=0.2, default=0.08)
    duration_sec: float = Field(gt=0.1, lt=5.0, default=1.2)


class LensDistortEffectConfig(BaseModel):
    enabled: bool = False
    duration_sec: float = Field(gt=0.05, lt=1.5, default=0.35)
    strength: float = Field(ge=0.0, le=0.5, default=0.18)


class RgbSplitEffectConfig(BaseModel):
    enabled: bool = False
    duration_sec: float = Field(gt=0.02, lt=1.0, default=0.18)
    offset_px: int = Field(ge=1, le=20, default=4)


class HighlightBloomEffectConfig(BaseModel):
    enabled: bool = False
    duration_sec: float = Field(gt=0.05, lt=2.0, default=0.55)
    luma_threshold: float = Field(ge=0.3, le=0.95, default=0.62)
    blur_px: int = Field(ge=3, le=64, default=18)
    intensity: float = Field(ge=0.0, le=2.0, default=0.85)
    weapon_bias: float = Field(ge=0.0, le=1.0, default=0.35)


class LightWrapEffectConfig(BaseModel):
    enabled: bool = False
    duration_sec: float = Field(gt=0.05, lt=2.0, default=0.4)
    radius: float = Field(ge=0.15, le=1.2, default=0.55)
    intensity: float = Field(ge=0.0, le=1.0, default=0.28)


class EffectsConfig(BaseModel):
    # Frame-space effects (ghost) before the camera moves the frame; screen-space
    # effects (flash, PiP card) after it so they stay stable.
    pipeline_order: list[str] = Field(
        default_factory=lambda: [
            "velocity",
            "ghost_freeze",
            "freeze_frame",
            "camera",
            "zoom",
            "shake",
            "motion_blur",
            "scope_vignette",
            "death_pip",
            "highlight_bloom",
            "light_wrap",
            "edge_glow",
            "kill_hit",
            "rgb_split",
            "lens_distort",
            "letterbox",
            "pip_inset",
            "color_grading",
        ]
    )
    velocity: VelocityEffectConfig = Field(default_factory=VelocityEffectConfig)
    camera: CameraEffectConfig = Field(default_factory=CameraEffectConfig)
    zoom: ZoomEffectConfig = Field(default_factory=ZoomEffectConfig)
    shake: ShakeEffectConfig = Field(default_factory=ShakeEffectConfig)
    color_grading: ColorGradingEffectConfig = Field(default_factory=ColorGradingEffectConfig)
    scope_vignette: ScopeVignetteEffectConfig = Field(default_factory=ScopeVignetteEffectConfig)
    death_pip: DeathPipEffectConfig = Field(default_factory=DeathPipEffectConfig)
    edge_glow: EdgeGlowEffectConfig = Field(default_factory=EdgeGlowEffectConfig)
    kill_hit: KillHitEffectConfig = Field(default_factory=KillHitEffectConfig)
    ghost_freeze: GhostFreezeEffectConfig = Field(default_factory=GhostFreezeEffectConfig)
    pip_inset: PipInsetEffectConfig = Field(default_factory=PipInsetEffectConfig)
    freeze_frame: FreezeFrameEffectConfig = Field(default_factory=FreezeFrameEffectConfig)
    motion_blur: MotionBlurEffectConfig = Field(default_factory=MotionBlurEffectConfig)
    letterbox: LetterboxEffectConfig = Field(default_factory=LetterboxEffectConfig)
    lens_distort: LensDistortEffectConfig = Field(default_factory=LensDistortEffectConfig)
    rgb_split: RgbSplitEffectConfig = Field(default_factory=RgbSplitEffectConfig)
    highlight_bloom: HighlightBloomEffectConfig = Field(default_factory=HighlightBloomEffectConfig)
    light_wrap: LightWrapEffectConfig = Field(default_factory=LightWrapEffectConfig)
