from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2

from src.detection.base import DetectionContext, Detector
from src.detection.registry import register_detector
from src.io.video_reader import get_video_info

log = logging.getLogger(__name__)


def _norm_name(name: str) -> str:
    return "".join(str(name).lower().split())


@register_detector("auto_gaming_yolo")
@dataclass
class AutoGamingYoloDetector(Detector):
    """Multi-class Valorant HUD detector using auto-gaming-montage-maker weights.

    Emission strategy: the killfeed persists on screen for ~5s, so naive
    per-frame emission with a fixed dedup window produces phantom duplicates
    (same kill re-emitted seconds later, timestamped mid-reload). Instead we
    emit only on rising edges (class absent -> present) with confidence
    hysteresis, then refine each event to the exact appearance frame at full
    framerate and subtract the killfeed UI latency so the timestamp points at
    the frag itself.
    """

    model_path: str = "models/auto_gaming_valorant.pt"
    confidence_threshold: float = 0.5
    region: tuple[float, float, float, float] = field(default_factory=lambda: (0.0, 0.0, 1.0, 1.0))
    sample_fps: int = 3
    # Presence hysteresis: a class counts as "already on screen" above this
    # (lower) confidence, suppressing re-emissions from conf flicker around
    # the emission threshold.
    presence_conf: float = 0.3
    # Minimum gap before the same raw class may fire again (guards against
    # brief detection dropouts on a persistent killfeed row).
    reemit_guard_sec: float = 1.5
    # The killfeed row appears after the actual frag; shift timestamps back
    # so beat-synced accents land on the kill, not the UI notification.
    killfeed_latency_sec: float = 0.35
    # Scan at full framerate around each sampled hit to find the exact
    # appearance frame (sampled detection alone quantizes by 1/sample_fps).
    refine_full_fps: bool = True
    class_mapping: dict[str, str] = field(
        default_factory=lambda: {
            "kill-1": "kill",
            "kill-2": "kill",
            "kill-3": "kill",
            "kill-4": "kill",
            "kill-5": "kill",
            "kill-6": "kill",
            "round-end": "round_boundary",
            "round-start": "round_boundary",
            "spectating": "game_state",
            "spike-plant": "objective",
        }
    )

    def __post_init__(self) -> None:
        if isinstance(self.region, list):
            self.region = tuple(float(x) for x in self.region)
        self._mapping_norm = {_norm_name(k): v for k, v in self.class_mapping.items()}

    def _crop_region(self, frame: Any) -> tuple[Any, int, int]:
        if self.region == (0.0, 0.0, 1.0, 1.0):
            return frame, 0, 0
        h, w, _ = frame.shape
        x1, y1, x2, y2 = self.region
        x1p, y1p = int(w * x1), int(h * y1)
        x2p, y2p = int(w * x2), int(h * y2)
        return frame[y1p:y2p, x1p:x2p], x1p, y1p

    def _kill_classes_in_frame(self, model: Any, frame: Any) -> dict[str, tuple[float, list[float]]]:
        """Return {raw_class: (conf, bbox)} for kill classes above presence_conf."""
        infer_frame, off_x, off_y = self._crop_region(frame)
        conf_floor = min(float(self.presence_conf), float(self.confidence_threshold))
        try:
            results = model.predict(infer_frame, conf=conf_floor, verbose=False, half=True)
        except TypeError:
            results = model.predict(infer_frame, conf=conf_floor, verbose=False)

        boxes = results[0].boxes if results else None
        out: dict[str, tuple[float, list[float]]] = {}
        if boxes is None or len(boxes) == 0:
            return out

        names = getattr(model, "names", {}) or {}
        for box in boxes:
            raw = _norm_name(str(names.get(int(box.cls[0]), f"class_{int(box.cls[0])}")))
            if self._mapping_norm.get(raw) != "kill":
                continue
            conf = float(box.conf[0])
            if raw not in out or conf > out[raw][0]:
                x1b, y1b, x2b, y2b = box.xyxy[0].cpu().numpy()
                out[raw] = (
                    conf,
                    [float(x1b + off_x), float(y1b + off_y), float(x2b + off_x), float(y2b + off_y)],
                )
        return out

    def _refine_appearance_frame(
        self, cap: Any, model: Any, raw_class: str, hit_frame: int, step: int
    ) -> int:
        """Scan (hit_frame - step, hit_frame] at full fps; return earliest frame with the class."""
        start = max(0, hit_frame - step + 1)
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(start))
        earliest = hit_frame
        for fi in range(start, hit_frame + 1):
            ret, frame = cap.read()
            if not ret:
                break
            if raw_class in self._kill_classes_in_frame(model, frame):
                earliest = fi
                break
        return earliest

    def detect(self, ctx: DetectionContext) -> list[dict[str, Any]]:
        try:
            from ultralytics import YOLO
        except ImportError:
            log.error("ultralytics required for auto_gaming_yolo")
            return []

        project_root = Path(__file__).resolve().parents[2]
        mp = Path(self.model_path)
        resolved = (project_root / mp).resolve() if not mp.is_absolute() else mp
        if not resolved.exists():
            log.warning("auto_gaming_yolo model not found: %s", resolved)
            return []

        model = YOLO(str(resolved))
        info = get_video_info(ctx.video_path)
        fps = info.fps if info.fps > 0 else 60.0
        step = max(1, int(round(fps / max(1, self.sample_fps))))

        cap = cv2.VideoCapture(str(ctx.video_path))
        if not cap.isOpened():
            return []

        # Pass 1: sampled scan, emit on rising edges only.
        candidates: list[dict[str, Any]] = []
        prev_present: set[str] = set()
        last_emit_by_raw: dict[str, float] = {}
        frame_idx = 0
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                if frame_idx % step != 0:
                    frame_idx += 1
                    continue

                present = self._kill_classes_in_frame(model, frame)
                t_sec = float(frame_idx / fps)
                for raw, (conf, bbox) in present.items():
                    if raw in prev_present or conf < float(self.confidence_threshold):
                        continue
                    last_t = last_emit_by_raw.get(raw)
                    if last_t is not None and (t_sec - last_t) <= float(self.reemit_guard_sec):
                        continue
                    candidates.append(
                        {"frame": frame_idx, "raw": raw, "conf": conf, "bbox": bbox}
                    )
                    last_emit_by_raw[raw] = t_sec
                prev_present = set(present.keys())
                frame_idx += 1

            # Pass 2: refine each candidate to the exact appearance frame.
            if self.refine_full_fps and step > 1:
                for cand in candidates:
                    cand["frame"] = self._refine_appearance_frame(
                        cap, model, cand["raw"], int(cand["frame"]), step
                    )
        finally:
            cap.release()

        detections: list[dict[str, Any]] = []
        for cand in candidates:
            t_appear = float(cand["frame"]) / fps
            t_kill = max(0.0, t_appear - float(self.killfeed_latency_sec))
            detections.append(
                {
                    "video_index": ctx.video_index,
                    "timestamp_sec": t_kill,
                    "score": float(min(1.0, float(cand["conf"]))),
                    "event_type": "kill",
                    "source": "auto_gaming_yolo",
                    "bbox": cand["bbox"],
                    "raw_class": str(cand["raw"]),
                }
            )
        detections.sort(key=lambda d: d["timestamp_sec"])

        log.info("auto_gaming_yolo: events=%d video=%s", len(detections), ctx.video_path)
        return detections
