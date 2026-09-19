from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class GameState:
    is_alive: bool
    round_active: bool
    current_round: int
    kills_this_round: int


class ValorantStateTracker:
    """
    Lightweight, frame-local UI heuristic tracker.

    Design constraints:
    - Must never throw on malformed/empty frames.
    - Intended to be reinstantiated per video.
    """

    def __init__(self, fps: float = 60.0):
        self.fps = float(fps or 60.0)
        self.state = GameState(is_alive=True, round_active=True, current_round=1, kills_this_round=0)
        self._last_health_var = 0.0

    def update(self, frame: np.ndarray) -> GameState:
        try:
            if frame is None or not hasattr(frame, "shape"):
                return self.state

            h, w = int(frame.shape[0]), int(frame.shape[1])
            if h <= 0 or w <= 0:
                return self.state

            # 1) Health bar ROI (bottom-center)
            y1, y2 = int(h * 0.86), int(h * 0.91)
            x1, x2 = int(w * 0.42), int(w * 0.58)
            if y2 <= y1 or x2 <= x1:
                return self.state

            health_roi = frame[y1:y2, x1:x2]
            if health_roi.size == 0:
                return self.state

            gray = cv2.cvtColor(health_roi, cv2.COLOR_BGR2GRAY)
            variance = float(np.var(gray))
            self._last_health_var = variance

            # Active health bar tends to have higher contrast. Death/spectator UI is flatter.
            self.state.is_alive = variance > 800.0

            # 2) Round boundary heuristic (stub)
            # We keep this intentionally conservative to avoid flapping state.
            # Future iterations can replace this with template/OCR without changing the API.
            if not self.state.is_alive and self.state.round_active:
                self.state.round_active = False
                self.state.kills_this_round = 0
            elif self.state.is_alive and not self.state.round_active:
                self.state.round_active = True
                self.state.current_round += 1

            return self.state
        except Exception:
            # Hard fail-safe: never throw from tracker.
            return self.state

