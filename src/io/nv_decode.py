"""GPU (NVDEC via PyNvVideoCodec) frame decode with OpenCV fallback."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)


def read_rgb_frame_at(video_path: Path, t_sec: float, size: tuple[int, int]) -> np.ndarray | None:
    """Decode one RGB frame at ``t_sec``, resized to ``size`` (width, height).

    Prefers PyNvVideoCodec NVDEC when available; falls back to OpenCV.
    """
    path = Path(video_path)
    if not path.is_file():
        return None
    frame = _try_pynv_rgb(path, t_sec=t_sec, size=size)
    if frame is not None:
        return frame
    return _opencv_rgb(path, t_sec=t_sec, size=size)


def _opencv_rgb(video_path: Path, *, t_sec: float, size: tuple[int, int]) -> np.ndarray | None:
    cap = cv2.VideoCapture(str(video_path))
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(t_sec)) * 1000.0)
        ok, bgr = cap.read()
    finally:
        cap.release()
    if not ok or bgr is None:
        return None
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)


def _try_pynv_rgb(video_path: Path, *, t_sec: float, size: tuple[int, int]) -> np.ndarray | None:
    try:
        import PyNvVideoCodec as nvc
    except ImportError:
        return None

    try:
        decoder = nvc.SimpleDecoder(
            str(video_path),
            gpu_id=0,
            use_device_memory=False,
            output_color_type=nvc.OutputColorType.RGB,
        )
        meta = decoder.get_stream_metadata()
        fps = float(getattr(meta, "average_fps", 0.0) or getattr(meta, "fps", 0.0) or 0.0)
        nframes = int(getattr(meta, "num_frames", 0) or len(decoder))
        if fps <= 0.0 or nframes <= 0:
            return None
        idx = int(round(max(0.0, float(t_sec)) * fps))
        idx = min(max(0, idx), nframes - 1)
        frames = decoder.get_batch_frames_by_index([idx])
        if not frames:
            return None
        raw = frames[0]
        arr = _frame_to_numpy(raw)
        if arr is None or arr.ndim != 3 or arr.shape[2] != 3:
            return None
        return cv2.resize(arr, size, interpolation=cv2.INTER_AREA)
    except Exception as exc:
        log.debug("nv_decode: PyNvVideoCodec failed for %s @ %.3fs (%s)", video_path.name, t_sec, exc)
        return None


def _frame_to_numpy(frame: object) -> np.ndarray | None:
    """Convert a DecodedFrame / tensor-like object to uint8 HWC RGB."""
    if isinstance(frame, np.ndarray):
        out = frame
    else:
        try:
            import torch

            if hasattr(frame, "__dlpack__"):
                out = torch.from_dlpack(frame).detach().cpu().numpy()
            elif hasattr(frame, "cpu"):
                out = frame.cpu().numpy()
            elif hasattr(frame, "numpy"):
                out = frame.numpy()
            else:
                out = np.asarray(frame)
        except Exception:
            try:
                out = np.asarray(frame)
            except Exception:
                return None
    if out.dtype != np.uint8:
        out = np.clip(out, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(out)
