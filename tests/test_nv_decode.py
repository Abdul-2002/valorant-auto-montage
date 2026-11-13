"""NVDEC frame reader falls back cleanly when PyNvVideoCodec is unavailable."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from src.io.nv_decode import read_rgb_frame_at


def test_should_fall_back_to_opencv_when_pynv_unavailable(tmp_path: Path) -> None:
    video = tmp_path / "missing.mp4"
    video.write_bytes(b"not-a-real-video")

    fake_frame = np.zeros((48, 64, 3), dtype=np.uint8)
    fake_frame[:, :] = (10, 20, 30)

    with (
        patch("src.io.nv_decode._try_pynv_rgb", return_value=None),
        patch("src.io.nv_decode._opencv_rgb", return_value=fake_frame) as ocv,
    ):
        out = read_rgb_frame_at(video, t_sec=1.25, size=(64, 48))

    assert out is not None
    assert out.shape == (48, 64, 3)
    ocv.assert_called_once()


def test_should_prefer_pynv_when_it_returns_a_frame(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    gpu_frame = np.full((48, 64, 3), 7, dtype=np.uint8)

    with (
        patch("src.io.nv_decode._try_pynv_rgb", return_value=gpu_frame) as nv,
        patch("src.io.nv_decode._opencv_rgb") as ocv,
    ):
        out = read_rgb_frame_at(video, t_sec=0.5, size=(64, 48))

    assert out is not None
    np.testing.assert_array_equal(out, gpu_frame)
    nv.assert_called_once()
    ocv.assert_not_called()
