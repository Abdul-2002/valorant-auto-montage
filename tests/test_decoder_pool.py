import tempfile
from pathlib import Path

import cv2
import numpy as np
from moviepy import VideoFileClip

from src.pipeline.decoder_pool import DecoderPool


def _write_video(path: Path, value: int) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 48))
    for i in range(60):
        writer.write(np.full((48, 64, 3), min(255, value + i), dtype=np.uint8))
    writer.release()


def test_should_close_least_recently_used_reader_when_limit_exceeded() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"v{i}.avi" for i in range(3)]
        for i, p in enumerate(paths):
            _write_video(p, 40 * i)
        clips = [VideoFileClip(str(p), audio=False) for p in paths]
        pool = DecoderPool(limit=2)
        for c in clips:
            pool.track(c.reader)
        try:
            assert pool.live_count == 2
            assert clips[0].reader.proc is None
            assert clips[1].reader.proc is not None and clips[2].reader.proc is not None
        finally:
            for c in clips:
                c.close()


def test_should_return_correct_frames_when_reader_was_closed_by_pool() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        a_path, b_path = Path(tmp) / "a.avi", Path(tmp) / "b.avi"
        _write_video(a_path, 0)
        _write_video(b_path, 120)
        a, b = VideoFileClip(str(a_path), audio=False), VideoFileClip(str(b_path), audio=False)
        pool = DecoderPool(limit=1)
        pool.track(a.reader)
        pool.track(b.reader)
        try:
            for t in (0.5, 1.0, 1.5):
                fa, fb = a.get_frame(t), b.get_frame(t)
                assert abs(float(fa.mean()) - int(30 * t)) <= 3
                assert abs(float(fb.mean()) - (120 + int(30 * t))) <= 3
            assert pool.live_count == 1
        finally:
            a.close()
            b.close()
