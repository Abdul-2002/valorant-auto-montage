#!/usr/bin/env python3
"""
Professional Valorant Montage Generator - MoviePy v2.2.1 Verified
Input: gameplay.mp4 + music.mp3 → Output: montage.mp4
Beat-synced kills, preset effects, consistent 3.2s rhythm.
"""

from __future__ import annotations

import argparse
import math
import sys
import tempfile
from pathlib import Path

import numpy as np
from moviepy import AudioFileClip, VideoFileClip, concatenate_videoclips
from pydub import AudioSegment

# Allow running as `python src/simple_montage.py` (sys.path would otherwise be `.../src`).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.detection.auto_gaming_yolo import AutoGamingYoloDetector
from src.detection.base import DetectionContext
from src.effects.base import EffectContext
from src.effects.color_grading import ColorGradingEffect
from src.effects.shake import ShakeEffect
from src.effects.velocity import VelocityEffect
from src.effects.zoom import ZoomEffect
from src.io.audio_loader import load_audio_segment
from src.pipeline.beat_analyzer import analyze_beats

# === CONFIG (Tweak these) ===
MODEL_PATH = "models/auto_gaming_valorant.pt"
CLIP_DURATION = 3.2  # Fixed seconds per kill clip
KILL_OFFSET = 1.6  # Kill centered in clip
SLOWMO_FACTOR = 0.4  # Slowmo on kill moment
SLOWMO_DURATION = 0.4  # Seconds of slowmo
ZOOM_MAX = 1.25  # Max zoom factor
ZOOM_DURATION = 0.3  # Zoom animation duration
SHAKE_PX = 4  # Shake amplitude
SHAKE_FRAMES = 8  # Shake duration in frames
BASS_BOOST_GAIN = 6.0  # dB boost on kills
GAMEPLAY_DUCK_DB = -12.0  # Duck gameplay audio on kills
CONFIDENCE_THRESHOLD = 0.5  # YOLO confidence threshold
BEAT_TOLERANCE = 0.2  # Seconds tolerance for beat snapping
# ===========================


def detect_kills(video_path: str, model_path: str) -> list[float]:
    """Detect kill timestamps using auto-gaming YOLO model."""
    vp = Path(video_path)
    if not vp.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    root = Path(__file__).resolve().parents[1]
    mp = Path(model_path)
    resolved_model = (root / mp).resolve() if not mp.is_absolute() else mp
    if not resolved_model.exists():
        raise FileNotFoundError(f"Model not found: {resolved_model}")

    detector = AutoGamingYoloDetector(model_path=str(resolved_model), confidence_threshold=CONFIDENCE_THRESHOLD)
    ctx = DetectionContext(video_index=0, video_path=vp.resolve(), assets_dir=root / "assets", config={})
    events = detector.detect(ctx)

    ts = sorted(float(e["timestamp_sec"]) for e in events if e.get("event_type") == "kill" and "timestamp_sec" in e)

    # Deduplicate nearby detections (HUD box persists for multiple frames).
    kills: list[float] = []
    for t in ts:
        if not kills or (t - kills[-1]) > 0.5:
            kills.append(t)
    return kills


def detect_beats(music_path: str) -> tuple[list[float], float]:
    """Detect beat timestamps in music using librosa (via existing beat analyzer)."""
    mp = Path(music_path)
    if not mp.exists():
        raise FileNotFoundError(f"Music not found: {music_path}")
    bm = analyze_beats(mp)
    return list(bm.beat_times), float(bm.tempo_bpm)


def align_kills_to_beats(kill_times: list[float], beat_times: list[float]) -> list[float]:
    """Snap kills to nearest beat if within tolerance."""
    if not beat_times:
        return kill_times
    aligned: list[float] = []
    for kill_t in kill_times:
        nearest = min(beat_times, key=lambda b: abs(b - kill_t))
        aligned.append(nearest if abs(nearest - kill_t) <= BEAT_TOLERANCE else kill_t)
    return aligned


def apply_effects(clip: VideoFileClip, kill_time_rel: float) -> VideoFileClip:
    """Apply preset effects using MoviePy v2.2.1 verified methods."""
    fps = int(round(float(getattr(clip, "fps", None) or 60.0)))

    # Use repo's production effects (v2-safe): zoom + smooth velocity ramp + shake + color grade.
    ctx = EffectContext(
        clip=clip,
        kill_timestamp=float(kill_time_rel),
        beat_timestamp=None,
        clip_duration=float(getattr(clip, "duration", None) or CLIP_DURATION),
        fps=fps,
        resolution=(int(getattr(clip, "w", 0) or 0), int(getattr(clip, "h", 0) or 0)),
        config={
            "_kill_slowmo_factor": float(SLOWMO_FACTOR),
            "_kill_slowmo_duration_sec": float(SLOWMO_DURATION),
        },
        kill_timestamps=(),
    )

    clip = ZoomEffect(enabled=True, max_zoom=float(ZOOM_MAX), duration_sec=float(ZOOM_DURATION)).apply(ctx)
    clip = VelocityEffect(enabled=True, kill_slowmo_factor=float(SLOWMO_FACTOR), kill_slowmo_duration_sec=float(SLOWMO_DURATION)).apply(
        EffectContext(**{**ctx.__dict__, "clip": clip})
    )
    clip = ShakeEffect(enabled=True, amplitude_px=int(SHAKE_PX), duration_frames=int(SHAKE_FRAMES)).apply(
        EffectContext(**{**ctx.__dict__, "clip": clip})
    )
    clip = ColorGradingEffect(enabled=True, saturation=1.15, contrast=1.1, brightness=0.015).apply(
        EffectContext(**{**ctx.__dict__, "clip": clip})
    )

    return clip


def _gain_db_from_linear(scale: float) -> float:
    s = float(scale)
    if s <= 0:
        return -120.0
    return 20.0 * math.log10(s)


def process_audio(*, music_path: str, gameplay_audio: AudioSegment, kill_times: list[float]) -> AudioSegment:
    """Mix music + gameplay with ducking & bass boost using pydub."""
    music = load_audio_segment(music_path)

    # Match duration (loop music if shorter).
    while music.duration_seconds + 1e-6 < gameplay_audio.duration_seconds:
        music += music
    music = music[: int(gameplay_audio.duration_seconds * 1000)]

    # Volume mix: music 80%, gameplay 60%.
    music = music.apply_gain(_gain_db_from_linear(0.8))
    gameplay = gameplay_audio.apply_gain(_gain_db_from_linear(0.6))

    # Duck gameplay around kills.
    window_ms = int(0.6 * 1000 / 2)
    for kill_t in kill_times:
        kill_ms = int(max(0.0, float(kill_t)) * 1000)
        start_ms = max(0, kill_ms - window_ms)
        end_ms = min(len(gameplay), kill_ms + window_ms)
        if start_ms >= end_ms:
            continue
        segment = gameplay[start_ms:end_ms]
        ducked = segment.apply_gain(float(GAMEPLAY_DUCK_DB))
        gameplay = gameplay[:start_ms] + ducked + gameplay[end_ms:]

    # Add bass boost SFX on kills (optional).
    bass_path = Path("editing_sfx/bass_boosted_fixed.mp3")
    if bass_path.exists():
        bass_sfx = load_audio_segment(bass_path).apply_gain(float(BASS_BOOST_GAIN))
        for kill_t in kill_times:
            kill_ms = int(max(0.0, float(kill_t)) * 1000)
            start_pos = max(0, kill_ms - 100)
            gameplay = gameplay.overlay(bass_sfx, position=start_pos)

    # Final mix.
    return music.overlay(gameplay)


def create_montage(video_path: str, music_path: str, output_path: str) -> None:
    """Main pipeline: detect → align → clip → effect → mix → render."""
    print(f"🎬 Processing: {video_path}")

    # 1. Detect kills
    print("🔍 Detecting kills...")
    kill_times = detect_kills(video_path, MODEL_PATH)
    print(f"✅ Found {len(kill_times)} kills")
    if not kill_times:
        print("❌ No kills detected.")
        sys.exit(1)

    # 2. Detect beats & align kills
    print("🎵 Detecting music beats...")
    beat_times, tempo = detect_beats(music_path)
    print(f"✅ Found {len(beat_times)} beats ({tempo:.1f} BPM)")
    aligned_kills = align_kills_to_beats(kill_times, beat_times)
    snapped = sum(1 for k, a in zip(kill_times, aligned_kills) if abs(k - a) <= 1e-2)
    print(f"✅ Snapped {snapped}/{len(kill_times)} kills to beats")

    # 3. Load video
    video = VideoFileClip(video_path)
    fps = float(getattr(video, "fps", None) or 60.0)

    # 4. Create & effect clips
    print("✂️ Creating clips...")
    clips: list[VideoFileClip] = []
    montage_kill_times: list[float] = []
    for i, (kill_t, aligned_t) in enumerate(zip(kill_times, aligned_kills)):
        start = max(0.0, float(aligned_t) - float(KILL_OFFSET))
        end = min(float(video.duration), float(aligned_t) + (float(CLIP_DURATION) - float(KILL_OFFSET)))
        clip = video.subclipped(start, end)
        kill_rel = float(kill_t) - float(start)
        clip = apply_effects(clip, kill_rel)
        clip = clip.with_duration(float(CLIP_DURATION))
        clips.append(clip)
        montage_kill_times.append(float(i) * float(CLIP_DURATION) + float(kill_rel))
        print(f"  Clip {i+1}/{len(kill_times)}")

    # 5. Concatenate clips
    print("🔗 Concatenating clips...")
    final_video = concatenate_videoclips(clips, method="compose")

    # 6. Audio processing (extract gameplay → pydub mix → attach)
    print("🔊 Mixing audio...")
    with tempfile.TemporaryDirectory(prefix="montage_") as td:
        td_path = Path(td)
        gameplay_wav = td_path / "gameplay.wav"
        mixed_mp3 = td_path / "mixed.mp3"

        if final_video.audio is None:
            gameplay_seg = AudioSegment.silent(duration=int(final_video.duration * 1000))
        else:
            final_video.audio.write_audiofile(
                str(gameplay_wav),
                fps=44100,
                nbytes=2,
                logger=None,
            )
            gameplay_seg = AudioSegment.from_file(str(gameplay_wav))

        mixed = process_audio(music_path=music_path, gameplay_audio=gameplay_seg, kill_times=montage_kill_times)
        mixed = mixed[: int(max(0.0, float(final_video.duration)) * 1000)]
        mixed.export(str(mixed_mp3), format="mp3")

        audio_clip = AudioFileClip(str(mixed_mp3))
        final_video = final_video.with_audio(audio_clip)

        # 7. Render
        print(f"💾 Rendering to {output_path}...")
        final_video.write_videofile(
            output_path,
            codec="libx264",
            audio_codec="aac",
            fps=fps,
            preset="medium",
            threads=4,
            logger=None,
        )

        audio_clip.close()

    video.close()
    final_video.close()
    for c in clips:
        try:
            c.close()
        except Exception:
            pass
    print(f"✅ Done! Montage saved to {output_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Professional Valorant Montage Generator")
    parser.add_argument("--video", required=True, help="Gameplay video path")
    parser.add_argument("--music", required=True, help="Music track path")
    parser.add_argument("--output", default="montage_final.mp4", help="Output path")
    args = parser.parse_args()
    create_montage(args.video, args.music, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

