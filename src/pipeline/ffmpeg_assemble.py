"""FFmpeg hard-cut assemble prototype (grade + NVENC, no Python frame loop).

Used when the script has only hard cuts and no pixel FX that require MoviePy.
This is the P1 speed path — frames stay inside FFmpeg.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.ai.schema import MontageScript
from src.config.models import AppConfig, OutputConfig
from src.pipeline.encode import encode_ffmpeg_params, resolve_lut


def _ffmpeg() -> str:
    from src.io.audio_loader import resolve_ffmpeg_exe

    return resolve_ffmpeg_exe()

log = logging.getLogger(__name__)

_PIXEL_FX = (
    "ghost_freeze",
    "glitter",
    "gun_outline",
    "pip_inset",
    "death_pip",
    "kill_hit",
    "highlight_bloom",
    "edge_glow",
    "rgb_split",
    "motion_blur",
    "lens_distort",
    "letterbox",
    "scope_vignette",
    "shake",
    "zoom",
    "camera",
    "velocity",
)


def can_use_ffmpeg_assemble(script: MontageScript | None) -> bool:
    """True when every cut is hard and no per-frame FX / remaps are required."""
    if script is None or not script.clips:
        return False
    for clip in script.clips:
        tr = clip.transition_to_next
        if tr is not None and str(tr.type) not in ("hard_cut",):
            return False
        if clip.time_knots and len(clip.time_knots) > 2:
            return False
        eff = clip.effects
        if eff is None:
            continue
        for name in _PIXEL_FX:
            cfg = getattr(eff, name, None)
            if cfg is not None and bool(getattr(cfg, "enabled", False)):
                return False
    return True


def assemble_hard_cuts_ffmpeg(
    *,
    video_paths: list[Path],
    music_path: Path | None,
    script: MontageScript,
    config: AppConfig,
    out_path: Path,
    work_dir: Path,
) -> Path:
    """Trim/concat clips with hard cuts, apply finishing LUT, encode with configured codec."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    list_file = work_dir / "ffmpeg_concat.txt"
    lines: list[str] = []
    for i, clip in enumerate(script.clips):
        src = video_paths[int(clip.video_index)]
        start = float(clip.start_sec)
        dur = max(0.05, float(clip.end_sec) - float(clip.start_sec))
        seg = work_dir / f"seg_{i:02d}.mp4"
        _trim_segment(src, seg, start_sec=start, duration_sec=dur, codec=str(config.output.codec))
        lines.append(f"file '{seg.resolve().as_posix()}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    concat_raw = work_dir / "concat_raw.mp4"
    _run(
        [
            _ffmpeg(),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(concat_raw),
        ]
    )

    try:
        lut_path = resolve_lut(config.output, work_dir)
    except FileNotFoundError:
        lut_path = None
    _encode_master(concat_raw, out_path, config.output, lut_path, music_path=music_path)
    log.info("ffmpeg_assemble: wrote %s (%d clips)", out_path.name, len(script.clips))
    return out_path


def _run(cmd: list[str], *, timeout: int = 3600) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)


def _trim_segment(src: Path, out: Path, *, start_sec: float, duration_sec: float, codec: str) -> None:
    nvenc = codec == "h264_nvenc"
    cmd = [
        _ffmpeg(),
        "-y",
        "-ss",
        f"{start_sec:.3f}",
        "-t",
        f"{duration_sec:.3f}",
        "-i",
        str(src),
        "-an",
        "-c:v",
        codec if codec else "libx264",
    ]
    if nvenc:
        cmd += ["-preset", "p4", "-rc", "vbr", "-cq", "19", "-b:v", "0"]
    else:
        cmd += ["-preset", "veryfast"]
    cmd.append(str(out))
    try:
        _run(cmd, timeout=600)
    except subprocess.CalledProcessError:
        _run(
            [
                _ffmpeg(),
                "-y",
                "-ss",
                f"{start_sec:.3f}",
                "-t",
                f"{duration_sec:.3f}",
                "-i",
                str(src),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                str(out),
            ],
            timeout=600,
        )


def _encode_master(
    raw: Path,
    out: Path,
    output: OutputConfig,
    lut_path: Path | None,
    *,
    music_path: Path | None,
) -> None:
    codec = str(output.codec or "libx264")
    params = encode_ffmpeg_params(output, lut_path, codec=codec)
    cmd: list[str] = [_ffmpeg(), "-y", "-i", str(raw)]
    if music_path is not None and music_path.is_file():
        cmd += ["-i", str(music_path), "-map", "0:v:0", "-map", "1:a:0?", "-shortest", "-c:a", "aac"]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", codec]
    if codec == "h264_nvenc":
        cmd += ["-preset", "p4"]
    else:
        cmd += ["-preset", "medium"]
    cmd += [*params, "-movflags", "+faststart", str(out)]
    try:
        _run(cmd)
    except subprocess.CalledProcessError:
        if codec != "h264_nvenc":
            raise
        cmd = [_ffmpeg(), "-y", "-i", str(raw)]
        if music_path is not None and music_path.is_file():
            cmd += ["-i", str(music_path), "-map", "0:v:0", "-map", "1:a:0?", "-shortest", "-c:a", "aac"]
        else:
            cmd += ["-an"]
        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            *encode_ffmpeg_params(output, lut_path, codec="libx264"),
            "-movflags",
            "+faststart",
            str(out),
        ]
        _run(cmd)
