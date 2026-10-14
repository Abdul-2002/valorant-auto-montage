import tempfile
from pathlib import Path

import cv2
import numpy as np

from src.detection.kill_frame_refine import first_banner_pop, mirror_symmetry, snap_kills_to_banner
from src.pipeline.types import DetectedEvent

W, H = 960, 540


def _background() -> np.ndarray:
    rng = np.random.default_rng(0)
    return (60 + rng.integers(0, 20, (H, W))).astype(np.uint8)


def _with_banner(gray: np.ndarray) -> np.ndarray:
    out = gray.copy()
    cv2.circle(out, (W // 2, int(H * 0.78)), 16, 245, -1)
    return out


def _frames(n: int, fps: float, change_at: int, painter) -> list[tuple[float, np.ndarray]]:
    bg = _background()
    return [(i / fps, painter(bg) if i >= change_at else bg.copy()) for i in range(n)]


def test_should_report_symmetric_patch_as_mirror_symmetric() -> None:
    patch = np.zeros((20, 20), dtype=np.float32)
    patch[5:15, 4:16] = 1.0
    assert mirror_symmetry(patch) > 0.99
    patch[:, 12:] = 0.0
    assert mirror_symmetry(patch) < 0.5


def test_should_find_onset_when_centred_banner_pops() -> None:
    frames = _frames(30, 60.0, 18, _with_banner)
    onset = first_banner_pop(frames, earliest_sec=0.0)
    assert onset is not None and abs(onset - 18 / 60.0) < 1e-6


def test_should_ignore_change_when_blob_is_off_centre() -> None:
    def body(g: np.ndarray) -> np.ndarray:
        out = g.copy()
        cv2.ellipse(out, (W // 2 + 14, int(H * 0.78)), (12, 30), 20, 0, 360, 230, -1)
        return out

    assert first_banner_pop(_frames(30, 60.0, 18, body), earliest_sec=0.0) is None


def test_should_ignore_change_when_whole_frame_shifts() -> None:
    def camera_turn(g: np.ndarray) -> np.ndarray:
        return np.clip(g.astype(np.int16) + 90, 0, 255).astype(np.uint8)

    assert first_banner_pop(_frames(30, 60.0, 18, camera_turn), earliest_sec=0.0) is None


def test_should_snap_late_stamp_back_and_keep_stamp_before_banner() -> None:
    fps, banner_frame = 30.0, 30
    bg = cv2.cvtColor(_background(), cv2.COLOR_GRAY2BGR)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pov.avi"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (W, H))
        for i in range(60):
            frame = bg.copy()
            if i >= banner_frame:
                cv2.circle(frame, (W // 2, int(H * 0.78)), 16, (245, 245, 245), -1)
            writer.write(frame)
        writer.release()
        events = [
            DetectedEvent(video_index=0, timestamp_sec=1.3, score=0.8, event_type="kill"),
            DetectedEvent(video_index=0, timestamp_sec=0.4, score=0.8, event_type="kill"),
        ]
        late, early = snap_kills_to_banner(events, [path])
    assert abs(late.timestamp_sec - banner_frame / fps) <= 1.5 / fps
    assert early.timestamp_sec == 0.4
