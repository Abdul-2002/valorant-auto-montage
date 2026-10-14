import tempfile
from pathlib import Path

import src.io.ffmpeg as ffmpeg_io


def _crop_command(codec: str) -> list[str]:
    calls: list[list[str]] = []
    original = ffmpeg_io.subprocess.run
    ffmpeg_io.subprocess.run = lambda cmd, **_kw: calls.append(cmd)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ffmpeg_io.crop_center_9x16_from_16x9(Path(tmp) / "in.mp4", Path(tmp) / "out.mp4", codec=codec)
    finally:
        ffmpeg_io.subprocess.run = original
    return calls[0]


def test_should_encode_nvenc_crop_at_constant_quality() -> None:
    cmd = _crop_command("h264_nvenc")
    assert cmd[cmd.index("-cq") + 1] == "19"
    assert cmd[cmd.index("-b:v") + 1] == "0"


def test_should_leave_libx264_on_its_crf_default() -> None:
    cmd = _crop_command("libx264")
    assert "-cq" not in cmd and "-b:v" not in cmd
