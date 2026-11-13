"""Soft-edge alpha from binary SAM masks (distance-transform feather)."""

from __future__ import annotations

import cv2
import numpy as np


def cleanup_mask(
    mask: np.ndarray,
    *,
    open_ksize: int = 5,
    close_ksize: int = 5,
) -> np.ndarray:
    """Morph open/close, then keep the largest connected component.

    Drops SAM speckles and tiny satellite blobs. Returns a bool mask the same
    shape as ``mask`` (all-False when nothing survives).
    """
    binary = (np.asarray(mask) > 0).astype(np.uint8)
    if binary.ndim != 2:
        raise ValueError(f"mask must be 2D, got shape {binary.shape}")
    if binary.max() == 0:
        return np.zeros(binary.shape, dtype=bool)

    open_k = max(1, int(open_ksize) | 1)
    close_k = max(1, int(close_ksize) | 1)
    opened = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_k, open_k))
    )
    closed = cv2.morphologyEx(
        opened, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_k, close_k))
    )
    n, labels, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    if n <= 1:
        return np.zeros(binary.shape, dtype=bool)
    largest = int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) + 1
    return labels == largest


def feather_mask_alpha(mask: np.ndarray, *, radius_px: float = 4.0) -> np.ndarray:
    """Return float32 alpha in [0, 1] with a soft band around the hard mask edge.

    Inside the solid region alpha≈1; outside≈0; within ``radius_px`` of the
    boundary the value ramps smoothly so cut-outs do not stair-step under
    motion blur or scale.
    """
    if radius_px <= 0.0:
        raise ValueError(f"radius_px must be > 0, got {radius_px}")

    binary = np.asarray(mask).astype(np.uint8)
    if binary.ndim != 2:
        raise ValueError(f"mask must be 2D, got shape {binary.shape}")
    if binary.max() == 0:
        return np.zeros(binary.shape, dtype=np.float32)

    # Distance outside the mask (0 on/inside foreground).
    outside = cv2.distanceTransform((1 - (binary > 0).astype(np.uint8)), cv2.DIST_L2, 3)
    # Distance inside the mask (0 on/outside foreground).
    inside = cv2.distanceTransform((binary > 0).astype(np.uint8), cv2.DIST_L2, 3)

    # Signed distance: positive inside, negative outside.
    signed = inside.astype(np.float32) - outside.astype(np.float32)
    # Map [-radius, +radius] → [0, 1] with a smoothstep for anti-aliased edges.
    t = np.clip((signed + float(radius_px)) / (2.0 * float(radius_px)), 0.0, 1.0)
    return (t * t * (3.0 - 2.0 * t)).astype(np.float32)
