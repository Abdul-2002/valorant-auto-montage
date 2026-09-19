from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from src.detection.base import DetectionContext, Detector
from src.detection.registry import register_detector
from src.io.video_reader import get_video_info


@dataclass
class _Template:
    name: str
    image_gray: np.ndarray
    mask: np.ndarray | None


def _load_template(path: Path) -> _Template | None:
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None

    mask: np.ndarray | None = None
    if img.ndim == 3 and img.shape[2] == 4:
        alpha = img[:, :, 3]
        mask = cv2.threshold(alpha, 0, 255, cv2.THRESH_BINARY)[1]
        img = img[:, :, :3]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return _Template(name=path.stem, image_gray=gray, mask=mask)


def _roi(frame_gray: np.ndarray, region: tuple[float, float, float, float]) -> np.ndarray:
    h, w = frame_gray.shape[:2]
    x1, y1, x2, y2 = region
    xa = int(w * x1)
    xb = int(w * x2)
    ya = int(h * y1)
    yb = int(h * y2)
    return frame_gray[ya:yb, xa:xb]


@register_detector("valorant_kill_feed")
class ValorantKillFeedTemplateDetector(Detector):
    def __init__(
        self,
        region: tuple[float, float, float, float] = (0.65, 0.0, 1.0, 0.15),
        confidence_threshold: float = 0.75,
        cooldown_sec: float = 0.5,
        sample_fps: int = 3,
        scales: list[float] | None = None,
    ) -> None:
        self.region = region
        self.confidence_threshold = confidence_threshold
        self.cooldown_sec = cooldown_sec
        self.sample_fps = sample_fps
        self.scales = scales or [0.8, 0.9, 1.0, 1.1, 1.2]

    def detect(self, ctx: DetectionContext) -> list[dict[str, Any]]:
        templates_dir = ctx.assets_dir / "templates"
        template_paths = [
            templates_dir / "kill_skull.png",
            templates_dir / "headshot_skull.png",
            templates_dir / "death_skull.png",
            templates_dir / "assist_icon.png",
        ]
        templates: list[_Template] = []
        for p in template_paths:
            if not p.exists():
                continue
            t = _load_template(p)
            if t is not None:
                templates.append(t)
        if not templates:
            return []

        info = get_video_info(ctx.video_path)
        fps = info.fps if info.fps > 0 else 60.0
        step = max(1, int(round(fps / max(1, self.sample_fps))))

        cap = cv2.VideoCapture(str(ctx.video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open video: {ctx.video_path}")

        events: list[dict[str, Any]] = []
        next_allowed_t = 0.0
        frame_idx = 0
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_idx % step != 0:
                    frame_idx += 1
                    continue

                t = frame_idx / fps
                if t < next_allowed_t:
                    frame_idx += 1
                    continue

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                roi_gray = _roi(gray, self.region)
                best: tuple[float, str] = (0.0, "kill")

                for tmpl in templates:
                    for scale in self.scales:
                        tw = max(1, int(round(tmpl.image_gray.shape[1] * scale)))
                        th = max(1, int(round(tmpl.image_gray.shape[0] * scale)))
                        if th >= roi_gray.shape[0] or tw >= roi_gray.shape[1]:
                            continue
                        resized = cv2.resize(tmpl.image_gray, (tw, th), interpolation=cv2.INTER_AREA)
                        mask = cv2.resize(tmpl.mask, (tw, th), interpolation=cv2.INTER_NEAREST) if tmpl.mask is not None else None

                        if mask is not None:
                            res = cv2.matchTemplate(roi_gray, resized, cv2.TM_CCOEFF_NORMED, mask=mask)
                        else:
                            res = cv2.matchTemplate(roi_gray, resized, cv2.TM_CCOEFF_NORMED)

                        _, max_val, _, _ = cv2.minMaxLoc(res)
                        if max_val > best[0]:
                            best = (float(max_val), tmpl.name)

                if best[0] >= self.confidence_threshold:
                    events.append(
                        {
                            "video_index": ctx.video_index,
                            "timestamp_sec": float(t),
                            "score": float(min(1.0, best[0])),
                            "event_type": "kill" if "kill" in best[1] or "headshot" in best[1] else best[1],
                            "source": "template",
                        }
                    )
                    next_allowed_t = t + self.cooldown_sec

                frame_idx += 1
        finally:
            cap.release()

        return events
