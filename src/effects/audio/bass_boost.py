from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydub import AudioSegment

from src.effects.base import AudioEffect, EffectContext
from src.io.audio_loader import load_audio_segment
from src.effects.registry import register_audio_effect


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


@register_audio_effect("bass_boost")
@dataclass
class BassBoostEffect(AudioEffect):
    enabled: bool = True
    on_drops_only: bool = True
    boost_db: float = 4.0
    kill_sfx_overlay: bool = True
    sfx_path: str | None = "assets/sfx/bass_hit.mp3"
    sfx_gain_db: float = -6.0

    def apply(self, audio: Any, ctx: EffectContext) -> Any:
        if not self.enabled:
            return audio
        if not isinstance(audio, dict):
            return audio
        mixed: AudioSegment | None = audio.get("mixed")
        if mixed is None:
            return audio
        # v1: drops-only is not implemented; honor config by treating on_drops_only=True as a no-op boost.
        out_bus = (mixed + float(self.boost_db)) if not self.on_drops_only else mixed

        ts = getattr(ctx, "kill_timestamps", ()) or ()
        if not self.kill_sfx_overlay or not ts:
            audio["mixed"] = out_bus
            return audio

        root = _project_root()
        rel = self.sfx_path or ""
        sfx_file = Path(rel)
        resolved = sfx_file if sfx_file.is_absolute() else (root / sfx_file).resolve()
        if not resolved.exists():
            audio["mixed"] = out_bus
            return audio

        try:
            hit = load_audio_segment(resolved)
        except Exception:
            audio["mixed"] = out_bus
            return audio

        # CRITICAL: format-match to the mix bus before overlay to avoid artifacts/static.
        # (Mismatch in frame_rate/channels/sample_width can produce audible noise.)
        hit = hit.set_frame_rate(out_bus.frame_rate).set_channels(out_bus.channels).set_sample_width(out_bus.sample_width)
        hit = hit + float(self.sfx_gain_db)

        out = out_bus
        for t in ts:
            pos_ms = int(max(0.0, float(t)) * 1000)
            if pos_ms >= len(out):
                continue
            out = out.overlay(hit, position=pos_ms)
        audio["mixed"] = out
        return audio
