from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from src.config.effect_models import (  # noqa: F401  (re-exported for existing imports)
    CameraEffectConfig,
    ColorGradingEffectConfig,
    DeathPipEffectConfig,
    EdgeGlowEffectConfig,
    EffectsConfig,
    FreezeFrameEffectConfig,
    GhostFreezeEffectConfig,
    HighlightBloomEffectConfig,
    KillHitEffectConfig,
    LensDistortEffectConfig,
    LetterboxEffectConfig,
    LightWrapEffectConfig,
    MotionBlurEffectConfig,
    PipInsetEffectConfig,
    RgbSplitEffectConfig,
    ScopeVignetteEffectConfig,
    ShakeEffectConfig,
    VelocityEffectConfig,
    ZoomEffectConfig,
)


class OutputConfig(BaseModel):
    target_duration_sec: int = Field(ge=5, le=60 * 30, default=90)
    formats: list[Literal["16:9", "9:16"]] = Field(default_factory=lambda: ["16:9", "9:16"])
    resolution: str = Field(default="1920x1080")
    fps: int = Field(ge=24, le=240, default=60)
    codec: str = Field(default="h264_nvenc")
    # Without an explicit rate NVENC defaults to ~2 Mbps: blocky, soft gameplay.
    video_bitrate: str = "16M"
    vertical_bitrate: str = "10M"
    # "procedural" writes the built-in teal/orange look; a path uses that .cube file; null disables.
    lut: Optional[str] = "procedural"
    lut_strength: float = Field(ge=0.0, le=1.0, default=0.6)
    sharpen: float = Field(ge=0.0, le=2.0, default=0.5)
    grain: int = Field(ge=0, le=30, default=5)
    vignette: bool = True
    audio_fade_out_sec: float = Field(ge=0.0, le=5.0, default=0.8)
    video_fade_out_sec: float = Field(ge=0.0, le=5.0, default=0.8)


class OverlaysConfig(BaseModel):
    """Montage-level overlays and text (kept inside the 9:16 center crop)."""

    enabled: bool = True
    light_leaks: bool = True
    light_leak_strength: float = Field(ge=0.0, le=1.0, default=0.35)
    flare_streaks: bool = True
    flare_strength: float = Field(ge=0.0, le=2.0, default=0.8)
    title_text: str = "VALORANT MONTAGE"
    title_sec: float = Field(gt=0.5, le=10.0, default=3.2)
    song_credit: bool = True
    multi_kill_callouts: bool = True
    # TTF/OTF font; empty tries Impact / Arial Bold / DejaVu Sans Bold.
    font_path: str = ""


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
    kill_dedupe_gap_sec: float = Field(ge=0.0, le=5.0, default=1.0)
    killfeed_latency_sec: float = Field(ge=0.0, le=2.0, default=0.1)
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
    visual_weight: float = Field(ge=0.0, le=1.0, default=0.8)
    audio_weight: float = Field(ge=0.0, le=1.0, default=0.2)
    dedup_window_sec: float = Field(ge=0.0, le=10.0, default=1.0)


class GeminiVideoDetectionConfig(BaseModel):
    enabled: bool = False
    model: str = "gemini-2.5-flash"
    min_excitement: float = Field(ge=0.0, le=1.0, default=0.3)


class GeminiKillVerifyConfig(BaseModel):
    """Short-clip Gemini visual accept/reject after candidate detection."""

    enabled: bool = False
    model: str = "gemini-2.5-flash-lite"
    clip_pre_sec: float = Field(ge=0.3, le=3.0, default=1.0)
    clip_post_sec: float = Field(ge=0.3, le=3.0, default=1.2)
    min_confidence: float = Field(ge=0.0, le=1.0, default=0.55)
    generate_timeout_sec: float = Field(ge=15.0, le=300.0, default=90.0)
    poll_timeout_sec: float = Field(ge=15.0, le=300.0, default=120.0)


class HudOcrTrigger(BaseModel):
    text: str
    region: tuple[float, float, float, float]


class HudOcrConfig(BaseModel):
    enabled: bool = False
    search_window_sec: float = Field(ge=0.5, le=5.0, default=2.0)
    triggers: list[HudOcrTrigger] = Field(default_factory=lambda: [
        HudOcrTrigger(text="HEADSHOT", region=(0.42, 0.87, 0.58, 0.95)),
        HudOcrTrigger(text="ACE", region=(0.40, 0.15, 0.60, 0.22)),
        HudOcrTrigger(text="CLUTCH", region=(0.38, 0.13, 0.62, 0.22)),
    ])


class DetectionConfig(BaseModel):
    # Kill detection is local YOLO (auto_gaming). Gemini is reserved for ai_director only.
    strategy: Literal["gemini", "yolo_legacy", "hybrid"] = "yolo_legacy"
    active_detectors: list[str] = Field(default_factory=lambda: ["auto_gaming_yolo"])
    gemini_video: GeminiVideoDetectionConfig = Field(default_factory=GeminiVideoDetectionConfig)
    gemini_kill_verify: GeminiKillVerifyConfig = Field(default_factory=GeminiKillVerifyConfig)
    hud_ocr: HudOcrConfig = Field(default_factory=HudOcrConfig)
    valorant_kill_feed: ValorantKillFeedConfig = Field(default_factory=ValorantKillFeedConfig)
    valorant_yolo: ValorantYoloConfig = Field(default_factory=ValorantYoloConfig)
    auto_gaming_yolo: AutoGamingYoloConfig = Field(default_factory=AutoGamingYoloConfig)
    audio_peaks: AudioPeaksConfig = Field(default_factory=AudioPeaksConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    sam_model_path: str = "models/sam2.1_t.pt"


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
    overlays: OverlaysConfig = Field(default_factory=OverlaysConfig)
    transitions: TransitionsConfig = Field(default_factory=TransitionsConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    ai_director: AIDirectorConfig = Field(default_factory=AIDirectorConfig)
