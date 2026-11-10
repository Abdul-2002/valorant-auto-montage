import tempfile
from pathlib import Path

import src.io.ffmpeg as ffmpeg_io
from src.config.models import OutputConfig
from src.pipeline.encode import encode_ffmpeg_params, finishing_lut_replaces_clip_grade, resolve_lut


def _crop_command(codec: str, video_bitrate: str | None = None) -> list[str]:
    calls: list[list[str]] = []
    original = ffmpeg_io.subprocess.run
    ffmpeg_io.subprocess.run = lambda cmd, **_kw: calls.append(cmd)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ffmpeg_io.crop_center_9x16_from_16x9(
                Path(tmp) / "in.mp4",
                Path(tmp) / "out.mp4",
                codec=codec,
                video_bitrate=video_bitrate,
            )
    finally:
        ffmpeg_io.subprocess.run = original
    return calls[0]


def test_should_scale_vertical_export_to_1080x1920() -> None:
    cmd = _crop_command("libx264", "10M")
    vf = cmd[cmd.index("-vf") + 1]
    assert "scale=1080:1920" in vf
    assert cmd[cmd.index("-b:v") + 1] == "10M"
    assert "-cq" not in cmd


def test_should_rate_nvenc_vertical_export_from_config() -> None:
    cmd = _crop_command("h264_nvenc", "10M")
    assert cmd[cmd.index("-rc") + 1] == "vbr"
    assert cmd[cmd.index("-b:v") + 1] == "10M"
    assert "-cq" not in cmd


def test_should_put_bitrate_and_lut_on_the_master_encode(tmp_path: Path) -> None:
    cfg = OutputConfig()
    lut = resolve_lut(cfg, tmp_path)
    params = encode_ffmpeg_params(cfg, lut, codec="h264_nvenc")
    vf = params[params.index("-vf") + 1]
    assert params[params.index("-b:v") + 1] == "16M"
    assert params[params.index("-rc") + 1] == "vbr"
    assert "lut3d" in vf
    assert "unsharp" in vf
    assert "vignette" in vf
    assert "noise" in vf
    assert finishing_lut_replaces_clip_grade(cfg) is True
    assert finishing_lut_replaces_clip_grade(OutputConfig(lut=None)) is False
