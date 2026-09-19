from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from ultralytics import YOLO

from src.detection.base import DetectionContext, Detector
from src.detection.game_state import ValorantStateTracker
from src.detection.registry import register_detector

log = logging.getLogger(__name__)


def _clip_roi_pixels(w: int, h: int, region: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = region
    x1p, y1p = int(w * x1), int(h * y1)
    x2p, y2p = int(w * x2), int(h * y2)
    x1p = max(0, min(w - 1, x1p))
    y1p = max(0, min(h - 1, y1p))
    x2p = max(1, min(w, x2p))
    y2p = max(1, min(h, y2p))
    if x2p <= x1p or y2p <= y1p:
        return (0, 0, w, h)
    return (x1p, y1p, x2p, y2p)


@register_detector("valorant_yolo")
class ValorantKillFeedYoloDetector(Detector):
    """
    YOLO-based kill feed icon detector (raw events output).

    Output schema (dict) is designed to be consumed by `src/detection/event_scorer.py`.
    Extra keys like `bbox` are kept for future enrichment/effects.
    """

    def __init__(
        self,
        model_path: str = "models/valorant_killfeed_yolo11n.pt",
        confidence_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        region: tuple[float, float, float, float] = (0.65, 0.0, 1.0, 0.15),
        sample_fps: int = 3,
        roi_upscale: float = 1.0,
    ):
        mp = Path(model_path)
        if not mp.exists():
            raise FileNotFoundError(f"valorant_yolo model_path not found: {mp}")

        self.model_path = str(mp)
        self.confidence_threshold = float(confidence_threshold)
        self.iou_threshold = float(iou_threshold)
        self.region = tuple(float(x) for x in region)  # type: ignore[assignment]
        self.sample_fps = int(sample_fps)
        self.roi_upscale = float(roi_upscale)

        self.model = YOLO(self.model_path)
        # Warmup (best-effort)
        try:
            self.model.predict(np.zeros((640, 640, 3), dtype=np.uint8), verbose=False)
        except Exception:
            log.debug("valorant_yolo warmup failed", exc_info=True)

    def detect(self, ctx: DetectionContext) -> list[dict[str, Any]]:
        cap = cv2.VideoCapture(str(ctx.video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {ctx.video_path}")

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 60.0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total_frames <= 0:
            total_frames = 0

        max_frames = int(ctx.config.get("_max_frames", 0) or 0)

        # Sampling stride (avoid per-frame YOLO at 60fps by default)
        target = max(1, int(self.sample_fps))
        stride = max(1, int(round(fps / target))) if target > 0 else 1

        tracker = ValorantStateTracker(fps=fps)
        out: list[dict[str, Any]] = []

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if max_frames > 0 and frame_idx >= max_frames:
                break

            if stride > 1 and (frame_idx % stride) != 0:
                frame_idx += 1
                continue

            try:
                state = tracker.update(frame)
                if not state.is_alive or not state.round_active:
                    frame_idx += 1
                    continue

                h, w = int(frame.shape[0]), int(frame.shape[1])
                x1p, y1p, x2p, y2p = _clip_roi_pixels(w, h, self.region)
                roi = frame[y1p:y2p, x1p:x2p]
                if roi is None or roi.size == 0:
                    frame_idx += 1
                    continue

                # Optional ROI upscaling for low-res videos
                scale = self.roi_upscale if self.roi_upscale and self.roi_upscale > 1.0 else 1.0
                infer_img = roi
                if scale != 1.0:
                    infer_img = cv2.resize(infer_img, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

                # Inference
                try:
                    results = self.model.predict(
                        infer_img,
                        conf=self.confidence_threshold,
                        iou=self.iou_threshold,
                        verbose=False,
                        half=True,
                        agnostic_nms=True,
                    )
                except TypeError:
                    # Some ultralytics builds reject half=... depending on device.
                    results = self.model.predict(
                        infer_img,
                        conf=self.confidence_threshold,
                        iou=self.iou_threshold,
                        verbose=False,
                        agnostic_nms=True,
                    )

                boxes = results[0].boxes if results else None
                if boxes is None or len(boxes) == 0:
                    frame_idx += 1
                    continue

                xyxy = boxes.xyxy.cpu().numpy()
                confs = boxes.conf.cpu().numpy()

                ts = float(frame_idx / fps) if fps > 0 else 0.0
                for (bx1, by1, bx2, by2), c in zip(xyxy, confs):
                    # Map back to full-frame coords (unscale -> offset)
                    if scale != 1.0:
                        bx1, by1, bx2, by2 = bx1 / scale, by1 / scale, bx2 / scale, by2 / scale
                    out.append(
                        {
                            "video_index": int(ctx.video_index),
                            "timestamp_sec": ts,
                            "score": float(np.clip(float(c), 0.0, 1.0)),
                            "event_type": "kill",
                            "source": "yolo",
                            "bbox": [float(bx1 + x1p), float(by1 + y1p), float(bx2 + x1p), float(by2 + y1p)],
                        }
                    )
            except Exception:
                # Detector must not crash the whole pipeline on a single bad frame.
                log.debug("valorant_yolo failed on frame %d", frame_idx, exc_info=True)
            finally:
                frame_idx += 1

        cap.release()
        log.info(
            "valorant_yolo: video=%s frames=%d stride=%d raw_events=%d",
            str(ctx.video_path),
            frame_idx,
            stride,
            len(out),
        )
        return out

