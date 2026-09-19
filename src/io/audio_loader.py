from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from pydub import AudioSegment


def resolve_ffmpeg_exe() -> str:
    """Return a working ffmpeg binary (imageio static build preferred on Windows)."""
    for key in ("FFMPEG_BINARY", "IMAGEIO_FFMPEG_EXE"):
        val = os.environ.get(key, "").strip()
        if val and Path(val).is_file():
            return val

    env_bin = Path.home() / ".conda/envs/valorant-montage/ffmpeg-bin/ffmpeg.exe"
    if env_bin.is_file():
        return str(env_bin)

    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and Path(bundled).is_file():
            return bundled
    except Exception:
        pass

    found = shutil.which("ffmpeg")
    if found:
        return found
    raise RuntimeError("ffmpeg not found; install ffmpeg or set FFMPEG_BINARY")


def load_audio_segment(path: str | Path, *, sample_rate: int = 44100) -> AudioSegment:
    """
    Load audio into pydub without relying on ffprobe.

    Conda-forge ffmpeg/ffprobe on Windows can fail with DLL errors; pydub's
    ``from_file`` needs ffprobe for compressed formats. We decode via ffmpeg
    to PCM WAV, which pydub reads natively.
    """
    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(f"audio not found: {src}")

    if src.suffix.lower() == ".wav":
        return AudioSegment.from_wav(str(src))

    ffmpeg = resolve_ffmpeg_exe()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        tmp = Path(tf.name)

    try:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(src),
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                str(sample_rate),
                "-ac",
                "2",
                str(tmp),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return AudioSegment.from_wav(str(tmp))
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
