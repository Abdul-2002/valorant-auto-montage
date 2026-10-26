"""Element jigsaw transition, after Rocklan's tutorial and Rafi's 01_portfolio_gig @0:11.

The incoming clip's first frame is split into scene elements: its gun
(``WEAPON_LABEL``), SAM scene segments (labels 2+) and the rest of the frame
(``REST_LABEL``). Over the outgoing clip's last beat each element slides in
from its nearest frame edge (the gun comes up from below), two-thirds of a
beat apart, with motion smear, and the rest lands on the cut, so the incoming clip
continues from the assembled frame. Duration-preserving: only the outgoing
tail is restyled. Refs: https://www.youtube.com/watch?v=gk_z0ZZxk94
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

log = logging.getLogger(__name__)

REST_LABEL = 0
WEAPON_LABEL = 1
PIECE_TRAVEL_SEC = 0.42
# Landing gap as a fraction of a beat. Half a beat still read fast on run 27.
_STAGGER_BEAT_FRAC = 2.0 / 3.0
FALLBACK_BEAT_SEC = 0.43
# Fixed layout (fractions of w/h) when no scene segmentation is available.
_GUN_BOX = (0.50, 0.58, 0.86)
_LEFT_STRIP_X = 0.18
_TOP_BAND_Y = 0.16
_RIGHT_STRIP_X = 0.86
_MAX_SMEAR_PX = 60
_FEATHER_SIGMA = 1.5
_PAD_PX = 8


@dataclass(frozen=True)
class Piece:
    rgb: np.ndarray  # uint8 crop of the incoming frame
    alpha: np.ndarray  # float32 crop, same height/width
    x0: int
    y0: int
    dx: float  # start offset in px; the piece slides from (dx, dy) to (0, 0)
    dy: float


def _ease_out(u: float) -> float:
    # Cubic: a quartic finishes ~94% of the slide in the first half, so the piece snaps in.
    return 1.0 - (1.0 - u) ** 3


def fixed_piece_labels(h: int, w: int) -> np.ndarray:
    """Gun zone, left strip, top band, right strip; the centre is the rest."""
    labels = np.zeros((h, w), dtype=np.uint8)
    labels[:, : int(_LEFT_STRIP_X * w)] = 2
    labels[: int(_TOP_BAND_Y * h), int(_LEFT_STRIP_X * w) :] = 3
    labels[int(_TOP_BAND_Y * h) :, int(_RIGHT_STRIP_X * w) :] = 4
    x0, y0, x1 = _GUN_BOX
    labels[int(y0 * h) :, int(x0 * w) : int(x1 * w)] = WEAPON_LABEL
    return labels


def load_piece_labels(path: str | None, w: int, h: int) -> np.ndarray:
    """Baked piece map for a jigsaw cut, or the fixed layout when missing/unreadable."""
    if path:
        raw = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if raw is not None:
            # Once ultralytics is imported its cv2.imread patch returns grayscale as (H, W, 1).
            raw = raw.reshape(raw.shape[:2])
            return raw if raw.shape == (h, w) else cv2.resize(raw, (w, h), interpolation=cv2.INTER_NEAREST)
        log.warning("jigsaw: piece map %s unreadable; using fixed layout", path)
    return fixed_piece_labels(h, w)


def entry_offset(mask: np.ndarray, *, from_bottom: bool) -> tuple[float, float]:
    """Start offset that puts the piece just past its nearest frame edge."""
    h, w = mask.shape
    ys, xs = np.nonzero(mask)
    if from_bottom:
        return 0.0, float(h - ys.min())
    cx, cy = float(xs.mean()) / w, float(ys.mean()) / h
    side = min((cx, "left"), (1.0 - cx, "right"), (cy, "top"), (1.0 - cy, "bottom"))[1]
    return {
        "left": (-float(xs.max() + 1), 0.0),
        "right": (float(w - xs.min()), 0.0),
        "top": (0.0, -float(ys.max() + 1)),
        "bottom": (0.0, float(h - ys.min())),
    }[side]


def build_pieces(frame_b: np.ndarray, labels: np.ndarray) -> list[Piece]:
    """One piece per non-rest label, in label (arrival) order."""
    h, w = labels.shape
    pieces: list[Piece] = []
    for label in sorted(int(v) for v in np.unique(labels) if v != REST_LABEL):
        mask = labels == label
        ys, xs = np.nonzero(mask)
        x0, y0 = max(0, int(xs.min()) - _PAD_PX), max(0, int(ys.min()) - _PAD_PX)
        x1, y1 = min(w, int(xs.max()) + 1 + _PAD_PX), min(h, int(ys.max()) + 1 + _PAD_PX)
        alpha = cv2.GaussianBlur(mask[y0:y1, x0:x1].astype(np.float32), (0, 0), _FEATHER_SIGMA)
        dx, dy = entry_offset(mask, from_bottom=label == WEAPON_LABEL)
        pieces.append(Piece(frame_b[y0:y1, x0:x1].copy(), alpha, x0, y0, dx, dy))
    return pieces


def _paste(out: np.ndarray, piece: Piece, u: float) -> None:
    """Composite one piece into ``out`` (float32, in place) at progress ``u``."""
    lag = 1.0 - _ease_out(u)
    ox, oy = int(round(piece.dx * lag)), int(round(piece.dy * lag))
    alpha = piece.alpha
    rgb = piece.rgb.astype(np.float32) * alpha[..., None]
    k = int(round(_MAX_SMEAR_PX * (1.0 - u)))
    if k > 1:
        ksize = (k, 1) if piece.dx else (1, k)
        rgb, alpha = cv2.blur(rgb, ksize), cv2.blur(alpha, ksize)
    h, w = out.shape[:2]
    ph, pw = alpha.shape
    px, py = piece.x0 + ox, piece.y0 + oy
    fx0, fy0, fx1, fy1 = max(0, px), max(0, py), min(w, px + pw), min(h, py + ph)
    if fx1 <= fx0 or fy1 <= fy0:
        return
    sx, sy = fx0 - px, fy0 - py
    a = alpha[sy : sy + fy1 - fy0, sx : sx + fx1 - fx0, None]
    region = out[fy0:fy1, fx0:fx1]
    region *= 1.0 - a
    region += rgb[sy : sy + fy1 - fy0, sx : sx + fx1 - fx0]


def _blend_rest(out: np.ndarray, frame_b: np.ndarray, rest_mask: np.ndarray, u: float) -> None:
    """Rest of the incoming frame lands last with a vertical streak (Rafi's centre smear)."""
    b = frame_b.astype(np.float32)
    k = int(round(_MAX_SMEAR_PX * (1.0 - u)))
    layer = cv2.blur(b, (1, k)) if k > 1 else b
    a = cv2.GaussianBlur(rest_mask.astype(np.float32), (0, 0), _FEATHER_SIGMA)[..., None] * _ease_out(u)
    out *= 1.0 - a
    out += layer * a


def piece_starts(n_events: int, beat_sec: float, max_tail_sec: float) -> list[float]:
    """Start time of each event relative to the cut; landings are two-thirds of a beat apart."""
    travel = min(PIECE_TRAVEL_SEC, max(0.0, max_tail_sec))
    room = max(0.0, max_tail_sec - travel) / max(1, n_events - 1)
    stagger = min(float(beat_sec) * _STAGGER_BEAT_FRAC, room)
    return [-(n_events - 1 - k) * stagger - travel for k in range(n_events)]


def jigsaw_tail_frame(
    frame_a: np.ndarray, frame_b: np.ndarray, pieces: list[Piece], rest_mask: np.ndarray, r: float, starts: list[float]
) -> np.ndarray:
    """Outgoing frame at ``r`` seconds before the cut (r < 0) with incoming elements composited."""
    out = frame_a.astype(np.float32)
    for piece, start in zip(pieces, starts):
        u = (r - start) / PIECE_TRAVEL_SEC
        if u > 0.0:
            _paste(out, piece, min(1.0, u))
    u_rest = (r - starts[-1]) / PIECE_TRAVEL_SEC
    if u_rest > 0.0:
        _blend_rest(out, frame_b, rest_mask, min(1.0, u_rest))
    return np.clip(out, 0, 255).astype(np.uint8)


def style_jigsaw_tail(clip: Any, *, incoming_frame: np.ndarray, labels: np.ndarray, beat_sec: float) -> Any:
    """Assemble the incoming clip's first frame, element by element, over the outgoing tail."""
    base_dur = float(getattr(clip, "duration", 0.0) or 0.0)
    pieces = build_pieces(incoming_frame, labels)
    rest_mask = labels == REST_LABEL
    starts = piece_starts(len(pieces) + 1, beat_sec if beat_sec > 0 else FALLBACK_BEAT_SEC, base_dur * 0.45)
    begin = base_dur + starts[0]

    def transform(get_frame, t):
        frame = get_frame(t)
        if float(t) < begin:
            return frame
        return jigsaw_tail_frame(frame, incoming_frame, pieces, rest_mask, float(t) - base_dur, starts)

    return clip.transform(transform)
