from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import logging
import time

from src.detection.base import DetectionContext, Detector
from src.detection.registry import register_detector
from src.io.video_reader import get_video_info


@register_detector("valorant_yolo_legacy")
@dataclass
class ValorantKillFeedYoloDetector(Detector):
    """
    Tier 2 detector (optional): Ultralytics YOLO11n fine-tuned for kill feed events.

    Notes:
    - This is only used if `config.detection.valorant_yolo.enabled == True`.
    - The model should be trained to detect kill-feed icons inside the ROI.
    """

    model_path: str = "models/valorant_killfeed_yolo11n.pt"
    confidence_threshold: float = 0.5
    region: tuple[float, float, float, float] = (0.65, 0.0, 1.0, 0.15)
    sample_fps: int = 3

    def detect(self, ctx: DetectionContext) -> list[dict[str, Any]]:
        log = logging.getLogger("valorant_yolo")
        try:
            from ultralytics import YOLO  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("ultralytics is required for valorant_yolo detector") from e

        project_root = Path(__file__).resolve().parents[2]
        mp = Path(self.model_path)
        model_path = (project_root / mp).resolve() if not mp.is_absolute() else mp
        if not model_path.exists():
            # Model weights are optional; when missing, skip rather than crashing the pipeline.
            return []

        model = YOLO(str(model_path))
        try:
            dev = getattr(getattr(model, "model", None), "device", None)
            log.warning("loaded weights=%s device=%s", model_path, dev)
        except Exception:
            log.warning("loaded weights=%s", model_path)

        info = get_video_info(ctx.video_path)
        fps = info.fps if info.fps > 0 else 60.0
        step = max(1, int(round(fps / max(1, self.sample_fps))))

        cap = cv2.VideoCapture(str(ctx.video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open video: {ctx.video_path}")

        events: list[dict[str, Any]] = []
        frame_idx = 0
        last_log_t = time.monotonic()
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_idx % step != 0:
                    frame_idx += 1
                    continue

                h, w = frame.shape[:2]
                x1, y1, x2, y2 = self.region
                xa, xb = int(w * x1), int(w * x2)
                ya, yb = int(h * y1), int(h * y2)
                roi = frame[ya:yb, xa:xb]
                if roi.size == 0:
                    frame_idx += 1
                    continue

                t = frame_idx / fps
                preds = model.predict(source=roi, conf=self.confidence_threshold, verbose=False, device=0)
                if not preds:
                    frame_idx += 1
                    continue

                p0 = preds[0]
                if p0.boxes is None:
                    frame_idx += 1
                    continue

                for b in p0.boxes:
                    conf = float(getattr(b, "conf", [0.0])[0]) if hasattr(b, "conf") else float(b.conf[0])
                    cls_id = int(getattr(b, "cls", [0])[0]) if hasattr(b, "cls") else int(b.cls[0])
                    events.append(
                        {
                            "video_index": ctx.video_index,
                            "timestamp_sec": float(t),
                            "score": float(min(1.0, conf)),
                            "event_type": f"class_{cls_id}",
                            "source": "yolo",
                        }
                    )

                now = time.monotonic()
                if now - last_log_t >= 10.0:
                    last_log_t = now
                    log.warning("t=%.1fs frame=%d events=%d", t, frame_idx, len(events))
                frame_idx += 1
        finally:
            cap.release()

        return events
