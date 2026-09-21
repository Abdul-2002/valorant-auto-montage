from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class OutputConfig(BaseModel):
    target_duration_sec: int = Field(ge=5, le=60 * 30, default=90)
    formats: list[Literal["16:9", "9:16"]] = Field(default_factory=lambda: ["16:9", "9:16"])
    resolution: str = Field(default="1920x1080")
    fps: int = Field(ge=24, le=240, default=60)
    codec: str = Field(default="h264_nvenc")


class VelocityEffectConfig(BaseModel):
    enabled: bool = True
    kill_slowmo_factor: float = Field(gt=0.05, lt=1.0, default=0.35)
    # 0.0 is valid: "no slowmo dip" (clean/punch recipes retime without slowmo).
    kill_slowmo_duration_sec: float = Field(ge=0.0, lt=5.0, default=0.6)
    transition_speedup_factor: float = Field(gt=0.25, lt=10.0, default=2.0)
    easing: str = Field(default="ease_in_out_cubic")


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
    lut_file: Optional[str] = None


class ScopeVignetteEffectConfig(BaseModel):
    enabled: bool = False
    duration_sec: float = Field(gt=0.05, lt=3.0, default=0.55)
    inner_radius: float = Field(ge=0.1, le=0.9, default=0.28)
    darkness: float = Field(ge=0.0, le=1.0, default=0.88)
    flash_scope: bool = True


class DeathPipEffectConfig(BaseModel):
    enabled: bool = False
    duration_sec: float = Field(gt=0.1, lt=2.5, default=0.95)
    scale: float = Field(ge=1.2, le=4.0, default=2.6)
    size_frac: float = Field(ge=0.15, le=0.5, default=0.36)
    margin_frac: float = Field(ge=0.01, le=0.1, default=0.025)
    border_px: int = Field(ge=0, le=16, default=5)
    desaturate: float = Field(ge=0.0, le=1.0, default=0.45)


class ImpactStylizeEffectConfig(BaseModel):
    enabled: bool = False
    duration_sec: float = Field(gt=0.05, lt=2.0, default=0.45)
    edge_strength: float = Field(ge=0.0, le=1.0, default=0.55)
    glow_strength: float = Field(ge=0.0, le=1.0, default=0.35)
    brightness_pulse: float = Field(ge=0.0, le=0.5, default=0.12)


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
    pipeline_order: list[str] = Field(
        default_factory=lambda: [
            "velocity",
            "freeze_frame",
            "zoom",
            "shake",
            "motion_blur",
            "scope_vignette",
            "death_pip",
            "highlight_bloom",
            "light_wrap",
            "impact_stylize",
            "lens_distort",
            "rgb_split",
            "letterbox",
            "color_grading",
        ]
    )
    velocity: VelocityEffectConfig = Field(default_factory=VelocityEffectConfig)
    zoom: ZoomEffectConfig = Field(default_factory=ZoomEffectConfig)
    shake: ShakeEffectConfig = Field(default_factory=ShakeEffectConfig)
    color_grading: ColorGradingEffectConfig = Field(default_factory=ColorGradingEffectConfig)
    scope_vignette: ScopeVignetteEffectConfig = Field(default_factory=ScopeVignetteEffectConfig)
    death_pip: DeathPipEffectConfig = Field(default_factory=DeathPipEffectConfig)
    impact_stylize: ImpactStylizeEffectConfig = Field(default_factory=ImpactStylizeEffectConfig)
    freeze_frame: FreezeFrameEffectConfig = Field(default_factory=FreezeFrameEffectConfig)
    motion_blur: MotionBlurEffectConfig = Field(default_factory=MotionBlurEffectConfig)
    letterbox: LetterboxEffectConfig = Field(default_factory=LetterboxEffectConfig)
    lens_distort: LensDistortEffectConfig = Field(default_factory=LensDistortEffectConfig)
    rgb_split: RgbSplitEffectConfig = Field(default_factory=RgbSplitEffectConfig)
    highlight_bloom: HighlightBloomEffectConfig = Field(default_factory=HighlightBloomEffectConfig)
    light_wrap: LightWrapEffectConfig = Field(default_factory=LightWrapEffectConfig)


class TransitionsConfig(BaseModel):
    enabled: bool = True
    default_type: str = "hard_cut"
    beat_drop_type: str = "flash_white"
    chorus_type: str = "whip_pan"
    verse_type: str = "hard_cut"
    flash_duration_sec: float = Field(gt=0.0, lt=2.0, default=0.05)
    xfade_duration_sec: float = Field(gt=0.0, lt=5.0, default=0.2)
    whip_duration_sec: float = Field(gt=0.05, lt=0.6, default=0.14)
    push_duration_sec: float = Field(gt=0.05, lt=0.6, default=0.12)
    whoosh_sfx_path: Optional[str] = "assets/sfx/whoosh.wav"
    whoosh_gain_db: float = Field(ge=-60.0, le=24.0, default=-10.0)


class AudioMixingConfig(BaseModel):
    enabled: bool = True
    music_volume_db: float = Field(ge=-60.0, le=24.0, default=0.0)
    game_sfx_volume_db: float = Field(ge=-60.0, le=24.0, default=-8.0)


class BassBoostConfig(BaseModel):
    enabled: bool = True
    # v1: default to always-on so the effect is not a no-op.
    # A future iteration can wire BeatMap/RMS into a real "drops only" mode.
    on_drops_only: bool = False
    boost_db: float = Field(ge=0.0, le=24.0, default=4.0)
    kill_sfx_overlay: bool = True
    sfx_path: Optional[str] = "assets/sfx/bass_hit.mp3"
    sfx_gain_db: float = Field(ge=-60.0, le=24.0, default=-6.0)


class AudioConfig(BaseModel):
    mixing: AudioMixingConfig = Field(default_factory=AudioMixingConfig)
    bass_boost: BassBoostConfig = Field(default_factory=BassBoostConfig)


class ValorantKillFeedConfig(BaseModel):
    region: tuple[float, float, float, float] = (0.65, 0.0, 1.0, 0.15)
    confidence_threshold: float = Field(ge=0.0, le=1.0, default=0.75)
    cooldown_sec: float = Field(ge=0.0, le=10.0, default=0.5)
    sample_fps: int = Field(ge=1, le=30, default=3)


class ValorantYoloConfig(BaseModel):
    enabled: bool = False
    model_path: str = "models/valorant_killfeed_yolo11n.pt"
    confidence_threshold: float = Field(ge=0.0, le=1.0, default=0.5)
    iou_threshold: float = Field(ge=0.0, le=1.0, default=0.45)
    region: tuple[float, float, float, float] = (0.65, 0.0, 1.0, 0.15)
    sample_fps: int = Field(ge=1, le=60, default=3)
    roi_upscale: float = Field(ge=1.0, le=8.0, default=1.0)


class AutoGamingYoloConfig(BaseModel):
    enabled: bool = True
    model_path: str = "models/auto_gaming_valorant.pt"
    confidence_threshold: float = Field(ge=0.0, le=1.0, default=0.5)
    region: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    sample_fps: int = Field(ge=1, le=60, default=3)
    presence_conf: float = Field(ge=0.0, le=1.0, default=0.3)
    reemit_guard_sec: float = Field(ge=0.0, le=30.0, default=1.5)
    killfeed_latency_sec: float = Field(ge=0.0, le=2.0, default=0.35)
    refine_full_fps: bool = True
    class_mapping: dict[str, str] = Field(
        default_factory=lambda: {
            "kill-1": "kill",
            "kill-2": "kill",
            "kill-3": "kill",
            "kill-4": "kill",
            "kill-5": "kill",
            "kill-6": "kill",
            "round-end": "round_boundary",
            "round-start": "round_boundary",
            "spectating": "game_state",
            "spike-plant": "objective",
        }
    )


class AudioPeaksConfig(BaseModel):
    rms_threshold_percentile: float = Field(ge=0.0, le=100.0, default=90.0)
    min_peak_distance_sec: float = Field(ge=0.0, le=5.0, default=0.3)
    use_hpss: bool = True


class ScoringConfig(BaseModel):
    visual_weight: float = Field(ge=0.0, le=1.0, default=0.7)
    audio_weight: float = Field(ge=0.0, le=1.0, default=0.3)
    dedup_window_sec: float = Field(ge=0.0, le=10.0, default=0.5)


class GeminiVideoDetectionConfig(BaseModel):
    enabled: bool = True
    model: str = "gemini-2.5-flash"
    min_excitement: float = Field(ge=0.0, le=1.0, default=0.3)


class HudOcrTrigger(BaseModel):
    text: str
    region: tuple[float, float, float, float]


class HudOcrConfig(BaseModel):
    enabled: bool = True
    search_window_sec: float = Field(ge=0.5, le=5.0, default=2.0)
    triggers: list[HudOcrTrigger] = Field(default_factory=lambda: [
        HudOcrTrigger(text="HEADSHOT", region=(0.42, 0.87, 0.58, 0.95)),
        HudOcrTrigger(text="ACE", region=(0.40, 0.15, 0.60, 0.22)),
        HudOcrTrigger(text="CLUTCH", region=(0.38, 0.13, 0.62, 0.22)),
    ])


class DetectionConfig(BaseModel):
    strategy: Literal["gemini", "yolo_legacy", "hybrid"] = "gemini"
    active_detectors: list[str] = Field(default_factory=lambda: ["gemini_video", "hud_ocr", "audio_peaks"])
    gemini_video: GeminiVideoDetectionConfig = Field(default_factory=GeminiVideoDetectionConfig)
    hud_ocr: HudOcrConfig = Field(default_factory=HudOcrConfig)
    valorant_kill_feed: ValorantKillFeedConfig = Field(default_factory=ValorantKillFeedConfig)
    valorant_yolo: ValorantYoloConfig = Field(default_factory=ValorantYoloConfig)
    auto_gaming_yolo: AutoGamingYoloConfig = Field(default_factory=AutoGamingYoloConfig)
    audio_peaks: AudioPeaksConfig = Field(default_factory=AudioPeaksConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)


class CreativeConfig(BaseModel):
    pacing: float = Field(ge=0.0, le=1.0, default=0.8)
    effect_intensity: float = Field(ge=0.0, le=1.0, default=0.7)
    slowmo_bias: float = Field(ge=0.0, le=1.0, default=0.6)
    flash_frequency: float = Field(ge=0.0, le=1.0, default=0.4)
    shake_intensity: float = Field(ge=0.0, le=1.0, default=0.5)
    zoom_aggression: float = Field(ge=0.0, le=1.0, default=0.5)
    color_warmth: float = Field(ge=0.0, le=1.0, default=0.6)
    beat_sync_strictness: float = Field(ge=0.0, le=1.0, default=0.8)
    variety: float = Field(ge=0.0, le=1.0, default=0.7)
    arc_enabled: bool = True


class GeminiConfig(BaseModel):
    api_key: str = ""
    model: str = "gemini-2.5-flash-lite"
    temperature: float = Field(ge=0.0, le=2.0, default=0.7)


class OpenAICompatibleConfig(BaseModel):
    base_url: str = "http://localhost:11434/v1"
    api_key: str = ""
    model: str = "qwen2.5:3b"
    temperature: float = Field(ge=0.0, le=2.0, default=0.7)


class LocalModelConfig(BaseModel):
    model_path: str = "models/qwen2.5-3b-instruct-q4_k_m.gguf"
    n_gpu_layers: int = 0
    n_ctx: int = Field(ge=512, le=131072, default=4096)
    temperature: float = Field(ge=0.0, le=2.0, default=0.7)


class AIDirectorConfig(BaseModel):
    enabled: bool = True
    provider: Literal["gemini", "openai_compatible", "local", "rule_only"] = "gemini"
    style_preset: str = "aggressive"
    creative_config: CreativeConfig = Field(default_factory=CreativeConfig)
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)
    openai_compatible: OpenAICompatibleConfig = Field(default_factory=OpenAICompatibleConfig)
    local: LocalModelConfig = Field(default_factory=LocalModelConfig)


class AppConfig(BaseModel):
    output: OutputConfig = Field(default_factory=OutputConfig)
    effects: EffectsConfig = Field(default_factory=EffectsConfig)
    transitions: TransitionsConfig = Field(default_factory=TransitionsConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    ai_director: AIDirectorConfig = Field(default_factory=AIDirectorConfig)
