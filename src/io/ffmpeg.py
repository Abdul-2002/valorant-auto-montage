from __future__ import annotations

import subprocess
from pathlib import Path

from src.io.audio_loader import resolve_ffmpeg_exe

# h264_nvenc defaults to ~2 Mbps, which macroblocks 1080p60 motion; use constant quality.
_NVENC_QUALITY_ARGS = ["-rc", "vbr", "-cq", "19", "-b:v", "0"]


def video_quality_args(codec: str) -> list[str]:
    """Extra ffmpeg rate-control args for ``codec`` (libx264 keeps its CRF default)."""
    return list(_NVENC_QUALITY_ARGS) if codec == "h264_nvenc" else []


def extract_audio_wav_mono(
    video_path: Path,
    out_wav: Path,
    *,
    sample_rate: int = 44100,
    timeout_sec: int = 60,
) -> None:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        resolve_ffmpeg_exe(),
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        str(out_wav),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout_sec)


def crop_center_9x16_from_16x9(
    in_mp4: Path,
    out_mp4: Path,
    *,
    codec: str = "libx264",
    fps: int | None = None,
    timeout_sec: int = 60 * 60,
) -> None:
    """
    Create a 9:16 center crop from a 16:9 input using FFmpeg.

    This intentionally runs as a separate FFmpeg encode rather than re-rendering the
    full MoviePy graph, which avoids a second pass through Python frame transforms.
    """
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    # width = ih*9/16, height = ih, x centered, y=0
    vf = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0"

    cmd: list[str] = [resolve_ffmpeg_exe(), "-y", "-i", str(in_mp4)]
    if fps is not None:
        cmd += ["-r", str(int(fps))]

    cmd += [
        "-vf",
        vf,
        "-c:v",
        codec,
        *video_quality_args(codec),
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(out_mp4),
    ]

    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout_sec)
