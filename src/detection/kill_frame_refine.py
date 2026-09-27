"""Local frame refine: lock Gemini candidates to the on-screen kill confirmation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from src.detection.base import DetectionContext, Detector
from src.detection.registry import register_detector

log = logging.getLogger(__name__)

# Valorant kill skull sits in the lower-center HUD band under the crosshair.
_KILL_ICON_REGION = (0.40, 0.45, 0.60, 0.78)
_WHITE_THR = 200
# Compact bright blob — not full-frame flash / smoke.
_MIN_AREA_FRAC = 0.0008
_MAX_AREA_FRAC = 0.06

# Death / spectator UI regions (normalized x1,y1,x2,y2).
_SWITCH_PLAYER_REGION = (0.02, 0.82, 0.32, 0.98)
_COMBAT_REPORT_REGION = (0.66, 0.12, 0.98, 0.72)
_SPECTATOR_BAR_REGION = (0.25, 0.88, 0.75, 0.99)


def _roi(frame: np.ndarray, region: tuple[float, float, float, float]) -> np.ndarray:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = region
    return frame[int(h * y1) : int(h * y2), int(w * x1) : int(w * x2)]


def _gray(roi: np.ndarray) -> np.ndarray:
    if roi.ndim == 3:
        return cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    return roi


def _frac_above(roi: np.ndarray, thr: int) -> float:
    if roi.size == 0:
        return 0.0
    g = _gray(roi)
    return float(np.count_nonzero(g > thr)) / float(g.size)


def _frac_below(roi: np.ndarray, thr: int) -> float:
    if roi.size == 0:
        return 0.0
    g = _gray(roi)
    return float(np.count_nonzero(g < thr)) / float(g.size)


def is_death_or_spectator_frame(frame: np.ndarray) -> bool:
    """True when the frame is death-cam / combat-report / spectator, not live POV.

    Rejects teammate death cams and "KILLED BY …" panels that Gemini sometimes
    stamps as kills. Heuristic only — no OCR.
    """
    bl = _roi(frame, _SWITCH_PLAYER_REGION)
    right = _roi(frame, _COMBAT_REPORT_REGION)
    bar = _roi(frame, _SPECTATOR_BAR_REGION)

    # Bottom-left "SWITCH PLAYER" / spectator prompt: dark plate + white glyphs.
    if _frac_above(bl, 200) >= 0.035 and _frac_below(bl, 45) >= 0.30:
        return True

    # Right-side combat report panel after you die.
    if _frac_above(right, 190) >= 0.028 and _frac_below(right, 50) >= 0.22:
        return True

    # Wide spectator chrome along the bottom edge.
    if _frac_above(bar, 200) >= 0.04 and _frac_below(bar, 40) >= 0.25:
        return True

    return False


def kill_skull_score(frame: np.ndarray) -> float:
    """0..1 confidence that the kill-confirm skull is visible this frame."""
    if is_death_or_spectator_frame(frame):
        return 0.0
    roi = _roi(frame, _KILL_ICON_REGION)
    if roi.size == 0:
        return 0.0
    gray = _gray(roi)
    _, binary = cv2.threshold(gray, _WHITE_THR, 255, cv2.THRESH_BINARY)
    area = float(np.count_nonzero(binary))
    frac = area / float(binary.size)
    if frac < _MIN_AREA_FRAC or frac > _MAX_AREA_FRAC:
        return 0.0
    # Prefer a compact central blob over scattered muzzle sparkles.
    ys, xs = np.where(binary > 0)
    if len(xs) < 8:
        return 0.0
    cx = float(np.mean(xs)) / max(1, binary.shape[1] - 1)
    cy = float(np.mean(ys)) / max(1, binary.shape[0] - 1)
    center_bias = 1.0 - min(1.0, ((cx - 0.5) ** 2 + (cy - 0.5) ** 2) ** 0.5)
    return float(np.clip(0.35 + 0.65 * center_bias, 0.0, 1.0))


@register_detector("kill_frame_refine")
@dataclass
class KillFrameRefineDetector(Detector):
    """Scan around Gemini timestamps; snap to the earliest strong kill-skull frame."""

    search_window_sec: float = 1.6
    sample_fps: float = 30.0
    min_score: float = 0.45

    def detect(self, ctx: DetectionContext) -> list[dict[str, Any]]:
        candidates: list[dict] = list(ctx.config.get("_candidate_events") or [])
        if not candidates:
            return []

        cap = cv2.VideoCapture(str(ctx.video_path))
        if not cap.isOpened():
            log.warning("kill_frame_refine: failed to open %s", ctx.video_path)
            return []

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        step = max(1, int(round(fps / max(1.0, float(self.sample_fps)))))
        half = float(self.search_window_sec) * 0.5

        out: list[dict[str, Any]] = []
        rejected_death = 0
        try:
            for cand in candidates:
                ts = float(cand.get("timestamp_sec", 0.0))
                start_f = max(0, int((ts - half) * fps))
                end_f = min(nframes - 1, int((ts + half) * fps))
                cap.set(cv2.CAP_PROP_POS_FRAMES, float(start_f))

                scored: list[tuple[float, float]] = []
                fi = start_f
                while fi <= end_f:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    if (fi - start_f) % step != 0:
                        fi += 1
                        continue
                    t = fi / fps
                    if is_death_or_spectator_frame(frame):
                        rejected_death += 1
                        fi += 1
                        continue
                    score = kill_skull_score(frame)
                    if score > 0.0:
                        scored.append((t, score))
                    fi += 1

                if scored:
                    peak = max(s for _, s in scored)
                    if peak >= float(self.min_score):
                        # Rising edge of the peak: earliest frame within 90% of peak.
                        thresh = peak * 0.9
                        cluster = [(t, s) for t, s in scored if s >= thresh]
                        best_t, best_s = min(cluster, key=lambda x: x[0])
                        out.append(
                            {
                                "video_index": ctx.video_index,
                                "timestamp_sec": float(best_t),
                                "score": float(best_s),
                                "event_type": str(cand.get("event_type") or "kill"),
                                "source": "kill_frame_refine",
                                "_original_timestamp_sec": ts,
                            }
                        )
                        log.warning(
                            "kill_frame_refine: %.3fs -> %.3fs (score=%.2f peak=%.2f)",
                            ts,
                            best_t,
                            best_s,
                            peak,
                        )
                else:
                    log.warning(
                        "kill_frame_refine: no valid skull near %.3fs (death/spectator rejected)",
                        ts,
                    )
        finally:
            cap.release()

        log.warning(
            "kill_frame_refine: refined %d/%d candidates for video %d (death_frames_skipped~%d)",
            len(out),
            len(candidates),
            ctx.video_index,
            rejected_death,
        )
        return out
