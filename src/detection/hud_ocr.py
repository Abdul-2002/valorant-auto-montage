from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from src.detection.base import DetectionContext, Detector
from src.detection.registry import register_detector

log = logging.getLogger(__name__)

# White pixel density threshold: if >15% of the thresholded ROI is white, text is likely present.
_WHITE_DENSITY_THRESHOLD: float = 0.15

# Minimum white pixel value for thresholding (Valorant HUD text is bright white).
_WHITE_THRESHOLD: int = 200


@register_detector("hud_ocr")
@dataclass
class HudOcrDetector(Detector):
    """
    Tier 1b detector: scans for Valorant HUD text (HEADSHOT, ACE, CLUTCH)
    to refine Gemini's ~1s-precision timestamps to exact frame precision (~0.03s).

    When _candidate_events is present in ctx.config, only scans around those
    timestamps (fast mode). Otherwise scans the entire video at sample_fps=2.
    """

    search_window_sec: float = 2.0
    triggers: list[dict] = field(default_factory=list)

    def detect(self, ctx: DetectionContext) -> list[dict[str, Any]]:
        candidate_events: list[dict] = ctx.config.get("_candidate_events", [])
        standalone_mode = len(candidate_events) == 0

        cap = cv2.VideoCapture(str(ctx.video_path))
        if not cap.isOpened():
            log.warning("hud_ocr: failed to open video %s", ctx.video_path)
            return []

        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        total_duration = total_frames / fps if fps > 0 else 0.0

        log.warning(
            "hud_ocr: video fps=%.1f total_frames=%d duration=%.1fs mode=%s candidates=%d",
            fps, total_frames, total_duration,
            "standalone" if standalone_mode else "candidate_refine",
            len(candidate_events),
        )

        events: list[dict[str, Any]] = []
        last_log_t = time.monotonic()

        if standalone_mode:
            # Scan entire video at 2 fps.
            sample_fps = 2.0
            step = max(1, int(round(fps / sample_fps)))
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
                    hit = self._check_frame(frame, t, ctx.video_index)
                    if hit:
                        events.append(hit)

                    now = time.monotonic()
                    if now - last_log_t >= 15.0:
                        last_log_t = now
                        log.warning("hud_ocr: scanned t=%.1fs events=%d", t, len(events))

                    frame_idx += 1
            finally:
                cap.release()

        else:
            # Candidate refinement mode: only scan +/- search_window_sec around each candidate.
            half_win = self.search_window_sec / 2.0
            try:
                for candidate in candidate_events:
                    ts = float(candidate.get("timestamp_sec", 0.0))
                    scan_start = max(0.0, ts - half_win)
                    scan_end = min(total_duration, ts + half_win)

                    start_frame = int(scan_start * fps)
                    end_frame = int(scan_end * fps)

                    # Seek to start frame.
                    cap.set(cv2.CAP_PROP_POS_FRAMES, float(start_frame))

                    best_hit: dict[str, Any] | None = None
                    for fi in range(start_frame, end_frame + 1):
                        ok, frame = cap.read()
                        if not ok:
                            break
                        t = fi / fps
                        hit = self._check_frame(frame, t, ctx.video_index)
                        if hit:
                            # Take the first/earliest confirmed frame in the window.
                            best_hit = hit
                            break

                    if best_hit:
                        # Mark the original candidate timestamp so highlight_detector can map it.
                        best_hit["_original_timestamp_sec"] = ts
                        events.append(best_hit)
                        log.warning(
                            "hud_ocr: refined %.3fs -> %.3fs (event_type=%s)",
                            ts, float(best_hit["timestamp_sec"]), best_hit.get("event_type"),
                        )
            finally:
                cap.release()

        log.warning("hud_ocr: found %d refined events", len(events))
        return events

    def _check_frame(self, frame: Any, t: float, video_index: int) -> dict[str, Any] | None:
        """Check a single frame for any HUD trigger text. Returns event dict or None."""
        h, w = frame.shape[:2]

        for trigger in self.triggers:
            text = str(trigger.get("text", ""))
            region = trigger.get("region", (0.0, 0.0, 1.0, 1.0))
            if not isinstance(region, (list, tuple)) or len(region) != 4:
                continue

            x1, y1, x2, y2 = region
            xa, xb = int(w * x1), int(w * x2)
            ya, yb = int(h * y1), int(h * y2)
            roi = frame[ya:yb, xa:xb]
            if roi.size == 0:
                continue

            if self._detect_white_text(roi):
                # Map trigger text to a canonical event_type.
                event_type = _TEXT_TO_EVENT_TYPE.get(text.upper(), "kill")
                return {
                    "video_index": video_index,
                    "timestamp_sec": float(t),
                    "score": 1.0,
                    "event_type": event_type,
                    "source": "hud_ocr",
                    "_trigger_text": text,
                }

        return None

    def _detect_white_text(self, roi: Any) -> bool:
        """Returns True if the ROI contains significant white text content."""
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
        _, binary = cv2.threshold(gray, _WHITE_THRESHOLD, 255, cv2.THRESH_BINARY)
        density = float(np.count_nonzero(binary)) / float(binary.size)
        return density > _WHITE_DENSITY_THRESHOLD


_TEXT_TO_EVENT_TYPE: dict[str, str] = {
    "HEADSHOT": "kill",
    "ACE": "ace",
    "CLUTCH": "clutch",
    "DOUBLE KILL": "double_kill",
    "TRIPLE KILL": "triple_kill",
    "QUADRA KILL": "quadra_kill",
    "FLAWLESS": "ace",
    "THRIFTY": "clutch",
}
