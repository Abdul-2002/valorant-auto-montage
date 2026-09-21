from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

import numpy as np
from moviepy import AudioFileClip, VideoFileClip, concatenate_videoclips
from pydub import AudioSegment

logger = logging.getLogger(__name__)

# Hard limits applied at render time regardless of what the script says.
_RENDER_MAX_SPEED: float = 2.0
_RENDER_MIN_SPEED: float = 0.3
_RENDER_MIN_SLOT_SEC: float = 0.5

from src.ai.schema import MontageScript
from src.config.models import AppConfig
from src.effects.base import EffectContext
from src.effects.registry import get_audio_effect, get_clip_effect
from src.io.audio_loader import load_audio_segment
from src.io.ffmpeg import crop_center_9x16_from_16x9
from src.pipeline.clip_sequencer import SelectedClip, select_clips
from src.pipeline.types import DetectedEvent


def _resolution(cfg: str) -> tuple[int, int]:
    w, h = cfg.lower().split("x")
    return int(w), int(h)

def _close_quietly(obj: Any) -> None:
    try:
        close = getattr(obj, "close", None)
        if callable(close):
            close()
    except Exception:
        pass


def _make_clip(video_path: Path, clip: SelectedClip) -> VideoFileClip:
    base = VideoFileClip(str(video_path))
    # MoviePy v2 renamed `subclip` -> `subclipped`.
    if hasattr(base, "subclip"):
        return base.subclip(clip.start_sec, clip.end_sec)  # type: ignore[attr-defined]
    return base.subclipped(clip.start_sec, clip.end_sec)  # type: ignore[attr-defined]


def _resized(clip: VideoFileClip, *, w: int, h: int) -> VideoFileClip:
    # MoviePy v2 renamed `resize` -> `resized`.
    if hasattr(clip, "resize"):
        return clip.resize(newsize=(w, h))  # type: ignore[attr-defined]
    return clip.resized(new_size=(w, h))  # type: ignore[attr-defined]


def _with_audio(clip: VideoFileClip, audio: AudioFileClip) -> VideoFileClip:
    # MoviePy v2 renamed `set_audio` -> `with_audio`.
    if hasattr(clip, "set_audio"):
        return clip.set_audio(audio)  # type: ignore[attr-defined]
    return clip.with_audio(audio)  # type: ignore[attr-defined]


def _with_duration(clip: VideoFileClip, duration: float) -> VideoFileClip:
    # Some MoviePy v2 clips can have `duration=None` unless explicitly set.
    if hasattr(clip, "set_duration"):
        return clip.set_duration(duration)  # type: ignore[attr-defined]
    return clip.with_duration(duration)  # type: ignore[attr-defined]


def _with_speed(clip: VideoFileClip, factor: float) -> VideoFileClip:
    f = float(factor)
    if f <= 0:
        return clip
    # MoviePy v2 uses with_speed; v1 often uses speedx.
    if hasattr(clip, "with_speed"):
        return clip.with_speed(f)  # type: ignore[attr-defined]
    if hasattr(clip, "speedx"):
        return clip.speedx(f)  # type: ignore[attr-defined]
    # Last resort: time_transform (kept for compatibility)
    return clip.time_transform(lambda t: t * f)


def _script_music_phase_offset_sec(script: MontageScript | None) -> float | None:
    """Earliest song-time (seconds) where the script places clip 0; trim music by this so video t=0 matches."""
    if script is None or not script.clips:
        return None
    starts: list[float] = []
    for c in script.clips:
        if c.output_start_sec is None:
            return None
        starts.append(float(c.output_start_sec))
    return min(starts)


def _script_planned_output_span_sec(script: MontageScript | None) -> float | None:
    """Song-time span covered by the script (last output_end - first output_start) when all clips have output fields."""
    if script is None or not script.clips:
        return None
    starts: list[float] = []
    ends: list[float] = []
    for c in script.clips:
        if c.output_start_sec is None or c.output_end_sec is None:
            return None
        starts.append(float(c.output_start_sec))
        ends.append(float(c.output_end_sec))
    return max(ends) - min(starts)


def _trim_music_to_script_phase(music: AudioSegment, offset_sec: float) -> AudioSegment:
    """Drop leading audio so montage t=0 aligns with song time ``offset_sec``."""
    off_ms = int(max(0.0, offset_sec) * 1000)
    if off_ms <= 0:
        return music
    if off_ms >= len(music):
        logger.warning(
            "assembler: music phase offset %.3fs >= track length; using full track (beat sync may be wrong).",
            offset_sec,
        )
        return music
    logger.info(
        "assembler: trimmed %.3fs from start of music to align video t=0 with script output timeline (song time).",
        offset_sec,
    )
    return music[off_ms:]


def _tint_head(clip: Any, *, color: tuple[int, int, int], duration_sec: float) -> Any:
    """Blend the first ``duration_sec`` of a clip toward a flat color (flash effect).

    Unlike inserting a ColorClip, this preserves the clip duration exactly,
    keeping cuts on the planned beat grid.
    """
    d = max(0.02, float(duration_sec))
    rgb = np.array(color, dtype=np.float32)

    def transform(get_frame, t):
        frame = get_frame(t)
        if t >= d:
            return frame
        a = 1.0 - (float(t) / d)
        return (frame.astype(np.float32) * (1.0 - a) + rgb * a).astype(np.uint8)

    return clip.transform(transform)


def _fade_tail_to_black(clip: Any, *, total_duration: float, fade_sec: float) -> Any:
    """Linear fade to black over the last ``fade_sec`` of the clip.

    A montage that ends on a raw frame with the music cut mid-phrase reads as
    a crash; this provides the outro. Duration is preserved exactly.
    """
    d = max(0.1, float(fade_sec))
    start = max(0.0, float(total_duration) - d)

    def transform(get_frame, t):
        frame = get_frame(t)
        if t <= start:
            return frame
        a = min(1.0, (float(t) - start) / d)
        return (frame.astype(np.float32) * (1.0 - a)).astype(np.uint8)

    return clip.transform(transform)


def _cropped(clip: VideoFileClip, *, x_center: int, y_center: int, width: int, height: int) -> VideoFileClip:
    # MoviePy v2 renamed `crop` -> `cropped`.
    if hasattr(clip, "crop"):
        return clip.crop(x_center=x_center, y_center=y_center, width=width, height=height)  # type: ignore[attr-defined]
    return clip.cropped(x_center=x_center, y_center=y_center, width=width, height=height)  # type: ignore[attr-defined]


def _extract_game_audio_from_clips(
    *,
    clips: list[Any],
    out_dir: Path,
) -> AudioSegment | None:
    """
    Extract and concatenate gameplay audio from already-subclipped MoviePy clips.

    Design constraints:
    - Avoid exporting the full assembled clip's audio (memory + runtime).
    - Work with MoviePy v2.2.1 API (AudioClip.write_audiofile).
    """
    if not clips:
        return None

    segments: list[AudioSegment] = []
    for i, c in enumerate(clips):
        a = getattr(c, "audio", None)
        if a is None:
            continue

        tmp = out_dir / f"_tmp_game_audio_{i:03d}.wav"
        try:
            a.write_audiofile(
                str(tmp),
                fps=44100,
                nbytes=2,
                logger=None,
            )
            segments.append(AudioSegment.from_file(str(tmp)))
        except Exception:
            logger.exception("assembler: failed extracting gameplay audio for clip %d", i)
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass

    if not segments:
        return None

    out = segments[0]
    for s in segments[1:]:
        out = out + s
    return out


def render_montage(
    *,
    video_paths: list[Path],
    music_path: Path | None,
    highlights: list[dict[str, Any]] | list[DetectedEvent],
    config: AppConfig,
    out_dir: Path,
    script: MontageScript | None = None,
    task_progress_cb: Callable[[float], None] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = _resolution(config.output.resolution)
    fps = int(config.output.fps)

    opened: list[Any] = []
    audio_clip: AudioFileClip | None = None
    assembled: Any | None = None

    # Normalize highlights
    dets: list[DetectedEvent] = []
    for item in highlights:
        if isinstance(item, DetectedEvent):
            dets.append(item)
        else:
            dets.append(DetectedEvent.model_validate(item))

    # Choose clip windows
    if script is not None and script.clips:
        selected = [
            SelectedClip(
                video_index=int(c.video_index),
                start_sec=float(c.start_sec),
                end_sec=float(c.end_sec),
                kill_timestamp_sec=float(c.kill_timestamp_sec),
                score=float(c.score),
            )
            for c in script.clips
        ]
    else:
        selected = select_clips(highlights=dets, target_duration_sec=config.output.target_duration_sec)
    if not selected:
        return

    try:
        clips: list[Any] = []
        for i, sel in enumerate(selected):
            vpath = video_paths[sel.video_index]
            vclip = _make_clip(vpath, sel)
            opened.append(vclip)
            vclip = _resized(vclip, w=w, h=h)
            clip_duration = float(getattr(vclip, "duration", None) or (sel.end_sec - sel.start_sec))

            # Beat-synced output: if script provides an explicit speed factor, apply it so
            # the clip's output duration matches its assigned beat slot in music time.
            # When kill-on-beat alignment speeds are present, skip global speed (velocity handles it).
            has_aligned_speed = (
                script is not None
                and script.clips
                and i < len(script.clips)
                and getattr(script.clips[i], "pre_kill_speed", None) is not None
            )

            if script is not None and script.clips and i < len(script.clips):
                sclip = script.clips[i]

                if not has_aligned_speed:
                    # Apply uniform speed factor (fallback when kill-on-beat isn't available).
                    raw_speed = getattr(sclip, "speed_factor", None)
                    if raw_speed is not None:
                        safe_speed = max(_RENDER_MIN_SPEED, min(_RENDER_MAX_SPEED, float(raw_speed)))
                        if abs(safe_speed - float(raw_speed)) > 0.01:
                            logger.warning(
                                "assembler: clamping speed_factor %.3f -> %.3f for clip %d at %.1fs",
                                float(raw_speed), safe_speed, i, sel.kill_timestamp_sec,
                            )
                        vclip = _with_speed(vclip, safe_speed)

                # Enforce output slot duration (with safety floor).
                if (
                    getattr(sclip, "output_start_sec", None) is not None
                    and getattr(sclip, "output_end_sec", None) is not None
                ):
                    raw_dur = float(sclip.output_end_sec) - float(sclip.output_start_sec)  # type: ignore[arg-type]
                    if raw_dur < _RENDER_MIN_SLOT_SEC:
                        logger.warning(
                            "assembler: output slot %.3fs < %.3fs for clip %d; using natural speed.",
                            raw_dur, _RENDER_MIN_SLOT_SEC, i,
                        )
                        vclip = _make_clip(video_paths[sel.video_index], sel)
                        vclip = _resized(vclip, w=w, h=h)
                        target_dur = clip_duration
                    else:
                        target_dur = max(_RENDER_MIN_SLOT_SEC, raw_dur)
                    vclip = _with_duration(vclip, target_dur)
                    clip_duration = target_dur
                else:
                    vclip = _with_duration(vclip, clip_duration)
            else:
                vclip = _with_duration(vclip, clip_duration)

            # Build EffectContext, injecting pre/post kill speeds when available.
            clip_config = config.model_dump(mode="json")
            clip_config["_src_duration_sec"] = float(sel.end_sec) - float(sel.start_sec)
            beat_ts: float | None = None
            if script is not None and script.clips and i < len(script.clips):
                sc = script.clips[i]
                if getattr(sc, "pre_kill_speed", None) is not None:
                    clip_config["_pre_kill_speed"] = float(sc.pre_kill_speed)  # type: ignore[arg-type]
                if getattr(sc, "post_kill_speed", None) is not None:
                    clip_config["_post_kill_speed"] = float(sc.post_kill_speed)  # type: ignore[arg-type]
                vel = getattr(sc.effects, "velocity", None) if sc.effects else None
                if vel is not None:
                    clip_config["_kill_slowmo_factor"] = float(vel.kill_slowmo_factor)
                    clip_config["_kill_slowmo_duration_sec"] = float(vel.kill_slowmo_duration_sec)
                kout = getattr(sc, "kill_output_time_sec", None)
                if kout is not None:
                    beat_ts = float(kout)

            ctx = EffectContext(
                clip=vclip,
                kill_timestamp=sel.kill_timestamp_sec - sel.start_sec,
                beat_timestamp=beat_ts,
                clip_duration=clip_duration,
                fps=fps,
                resolution=(w, h),
                config=clip_config,
                kill_timestamps=(),
            )

            # Apply clip effects in configured order.
            # Time-domain contract: velocity retimes the clip, so it anchors on the
            # SOURCE kill offset (ctx.kill_timestamp) and maps it to beat_timestamp.
            # Every effect after velocity must anchor on the OUTPUT-domain kill time
            # (beat_timestamp), otherwise zoom/shake fire at the wrong moment.
            for name in config.effects.pipeline_order:
                # When a MontageScript is present, allow per-clip effect overrides.
                if script is not None and i < len(script.clips):
                    script_eff = getattr(script.clips[i].effects, name, None)
                    eff_cfg = script_eff.model_dump(mode="json") if script_eff is not None else {}
                else:
                    eff_cfg = getattr(config.effects, name).model_dump(mode="json") if hasattr(config.effects, name) else {}
                if not eff_cfg or not eff_cfg.get("enabled", False):
                    continue
                eff = get_clip_effect(name).from_config(eff_cfg)
                anchor_kill = ctx.kill_timestamp
                if name != "velocity" and beat_ts is not None:
                    anchor_kill = beat_ts
                vclip = eff.apply(
                    EffectContext(
                        **{
                            **ctx.__dict__,
                            "clip": vclip,
                            "clip_duration": clip_duration,
                            "kill_timestamp": anchor_kill,
                        }
                    )
                )
                vclip = _with_duration(vclip, clip_duration)

            clips.append(vclip)

            if task_progress_cb:
                task_progress_cb(0.1 + 0.6 * ((i + 1) / len(selected)))

        # Apply transitions between clips.
        # CRITICAL: every transition must preserve the output timeline exactly.
        # Inserting flash frames or overlapping clips shifts all subsequent cuts off
        # the music beat grid (the audio runs on an absolute timeline). Flash
        # transitions are rendered as a tint on the head of the next clip; whip/push
        # are duration-preserving motion styles on clip tails/heads.
        from src.effects.transitions.motion_style import style_push_head, style_whip_head, style_whip_tail

        flash_dur = max(0.02, float(config.transitions.flash_duration_sec))
        whip_dur = max(0.05, float(getattr(config.transitions, "whip_duration_sec", 0.14) or 0.14))
        push_dur = max(0.05, float(getattr(config.transitions, "push_duration_sec", 0.12) or 0.12))
        whoosh_times_sec: list[float] = []
        styled: list[Any] = []
        for idx, clip in enumerate(clips):
            nxt = clip
            if idx > 0:
                prev_idx = idx - 1
                if script is not None and prev_idx < len(script.clips) and script.clips[prev_idx].transition_to_next is not None:
                    t_name = str(script.clips[prev_idx].transition_to_next.type)
                else:
                    t_name = config.transitions.default_type if config.transitions.enabled else "hard_cut"

                if t_name == "flash_white":
                    nxt = _tint_head(nxt, color=(255, 255, 255), duration_sec=flash_dur)
                elif t_name == "flash_black":
                    nxt = _tint_head(nxt, color=(0, 0, 0), duration_sec=flash_dur)
                elif t_name == "whip_pan":
                    nxt = style_whip_head(nxt, duration_sec=whip_dur)
                    whoosh_times_sec.append(sum(float(getattr(c, "duration", 0.0) or 0.0) for c in styled))
                elif t_name == "push":
                    nxt = style_push_head(nxt, duration_sec=push_dur)

            # Style whip on the outgoing tail before appending, when this clip
            # transitions via whip_pan to the next.
            if idx < len(clips) - 1:
                if script is not None and idx < len(script.clips) and script.clips[idx].transition_to_next is not None:
                    t_out = str(script.clips[idx].transition_to_next.type)
                else:
                    t_out = config.transitions.default_type if config.transitions.enabled else "hard_cut"
                if t_out == "whip_pan":
                    nxt = style_whip_tail(nxt, duration_sec=whip_dur)

            styled.append(nxt)

        assembled = concatenate_videoclips(styled, method="compose")

        # Audio pipeline
        audio_pack: dict[str, AudioSegment | None] = {"music": None, "game": None, "mixed": None}
        music_phase_sec = _script_music_phase_offset_sec(script)
        # Kill times must be in the MONTAGE timeline (t=0 at first clip), not absolute
        # song time: the music gets trimmed by music_phase_sec, so subtract it here or
        # every bass hit / duck lands late by the phase offset.
        phase = float(music_phase_sec or 0.0)
        kill_times: list[float] = []
        if script is not None and script.clips:
            for c in script.clips:
                out = c.output_start_sec
                end = c.output_end_sec
                if out is None or end is None:
                    continue
                span = max(1e-6, float(end) - float(out))
                kout = c.kill_output_time_sec
                if kout is not None:
                    kill_times.append(float(out) + float(kout) - phase)
                else:
                    kill_times.append(float(out) + 0.5 * span - phase)

        audio_ctx = EffectContext(
            clip=None,
            kill_timestamp=None,
            beat_timestamp=None,
            clip_duration=0.0,
            fps=fps,
            resolution=(w, h),
            config=config.model_dump(mode="json"),
            kill_timestamps=tuple(kill_times),
        )

        if music_path is not None and music_path.exists():
            music_seg = load_audio_segment(music_path)
            if music_phase_sec is not None:
                music_seg = _trim_music_to_script_phase(music_seg, music_phase_sec)
            audio_pack["music"] = music_seg

        # Extract gameplay audio (per-clip concatenation keeps memory stable).
        game_seg = _extract_game_audio_from_clips(clips=clips, out_dir=out_dir)
        if game_seg is not None:
            audio_pack["game"] = game_seg

        # Apply audio effects
        mix_cfg = config.audio.mixing.model_dump(mode="json")
        audio_pack = get_audio_effect("audio_mixing").from_config(mix_cfg).apply(audio_pack, audio_ctx)
        bass_cfg = config.audio.bass_boost.model_dump(mode="json")
        audio_pack = get_audio_effect("bass_boost").from_config(bass_cfg).apply(audio_pack, audio_ctx)

        # Optional whoosh SFX on whip transitions (skip silently if asset missing).
        mixed = audio_pack.get("mixed")
        whoosh_path = getattr(config.transitions, "whoosh_sfx_path", None)
        if mixed is not None and whoosh_times_sec and whoosh_path:
            wp = Path(str(whoosh_path))
            if not wp.is_file():
                wp = Path(__file__).resolve().parents[2] / str(whoosh_path)
            if wp.is_file():
                try:
                    whoosh = load_audio_segment(wp)
                    gain = float(getattr(config.transitions, "whoosh_gain_db", -10.0) or -10.0)
                    whoosh = whoosh + gain
                    for t_sec in whoosh_times_sec:
                        pos = max(0, int(float(t_sec) * 1000))
                        mixed = mixed.overlay(whoosh, position=pos)
                    audio_pack["mixed"] = mixed
                except Exception:
                    logger.exception("assembler: whoosh overlay failed; continuing without whoosh")

        if audio_pack.get("mixed") is not None:
            tmp_audio = out_dir / "mixed_audio.mp3"
            # Ensure audio does not outlive video; otherwise players freeze last frame.
            assembled_dur = float(getattr(assembled, "duration", None) or sum(c.end_sec - c.start_sec for c in selected))
            planned_span = _script_planned_output_span_sec(script)
            if planned_span is not None:
                delta_dur = assembled_dur - planned_span
                if abs(delta_dur) > 0.05:
                    logger.warning(
                        "assembler: final video duration %.3fs vs script output span %.3fs (delta %+.3fs). "
                        "Transitions or non-slot frames can shift on-beat cuts relative to the music grid.",
                        assembled_dur,
                        planned_span,
                        delta_dur,
                    )
            mixed = audio_pack["mixed"][: int(max(0.0, assembled_dur) * 1000)]
            # Outro: fade audio out and video to black so the montage ends
            # deliberately instead of stopping mid-phrase on a raw frame.
            mixed = mixed.fade_out(1800)
            assembled = _fade_tail_to_black(assembled, total_duration=assembled_dur, fade_sec=1.2)
            mixed.export(str(tmp_audio), format="mp3")
            audio_clip = AudioFileClip(str(tmp_audio))
            assembled = _with_audio(assembled, audio_clip)

        # Write outputs
        out_16 = out_dir / "montage_16x9.mp4"
        codec = config.output.codec or "libx264"
        # NVENC requires an ffmpeg build with NVENC enabled; libx264 is a safe fallback.
        try:
            if codec == "h264_nvenc":
                assembled.write_videofile(str(out_16), fps=fps, codec=codec, audio_codec="aac", preset="p4")
            else:
                assembled.write_videofile(str(out_16), fps=fps, codec=codec, audio_codec="aac", preset="medium")
        except OSError:
            # Common failure: ffmpeg missing NVENC encoder inside container.
            assembled.write_videofile(str(out_16), fps=fps, codec="libx264", audio_codec="aac", preset="medium")

        if "9:16" in config.output.formats:
            out_9 = out_dir / "montage_9x16.mp4"
            # Generate 9:16 from the already-rendered 16:9 via FFmpeg.
            # This avoids a second full MoviePy render (which would rerun Python-frame transforms).
            try:
                crop_center_9x16_from_16x9(in_mp4=out_16, out_mp4=out_9, codec=codec, fps=fps)
            except Exception:
                # Conservative fallback: keep behavior working even if ffmpeg crop fails.
                target_w = int(h * 9 / 16)
                cropped = _cropped(assembled, x_center=w // 2, y_center=h // 2, width=target_w, height=h)
                try:
                    if codec == "h264_nvenc":
                        cropped.write_videofile(str(out_9), fps=fps, codec=codec, audio_codec="aac", preset="p4")
                    else:
                        cropped.write_videofile(str(out_9), fps=fps, codec=codec, audio_codec="aac", preset="medium")
                except OSError:
                    cropped.write_videofile(str(out_9), fps=fps, codec="libx264", audio_codec="aac", preset="medium")
                finally:
                    _close_quietly(cropped)

        if task_progress_cb:
            task_progress_cb(0.95)
    finally:
        if audio_clip is not None:
            _close_quietly(audio_clip)
        if assembled is not None:
            _close_quietly(assembled)
        for c in reversed(opened):
            _close_quietly(c)
