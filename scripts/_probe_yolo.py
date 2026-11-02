"""Probe YOLO kill detections with half=True vs half=False on a real VOD frame."""
from __future__ import annotations

from pathlib import Path

import cv2
import torch
from ultralytics import YOLO

MODEL = Path("/app/models/auto_gaming_valorant.pt")
# Mid-size clip that previously had kills in older runs when detection worked.
CANDIDATES = sorted(Path("/videos").glob("*.mp4"), key=lambda p: p.stat().st_size)


def main() -> None:
    print("cuda", torch.cuda.is_available())
    print("model", MODEL.exists(), MODEL)
    model = YOLO(str(MODEL))
    print("names", model.names)

    video = next((p for p in CANDIDATES if 200_000_000 < p.stat().st_size < 400_000_000), CANDIDATES[0])
    print("video", video.name, video.stat().st_size)

    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 60
    # Sample ~40 frames across first 3 minutes
    hits_half = 0
    hits_full = 0
    raw_classes_half: set[str] = set()
    raw_classes_full: set[str] = set()
    for i in range(0, int(fps * 180), max(1, int(fps // 2))):
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(i))
        ok, frame = cap.read()
        if not ok:
            break
        for half, bucket, classes in (
            (True, "half", raw_classes_half),
            (False, "full", raw_classes_full),
        ):
            try:
                res = model.predict(frame, conf=0.25, verbose=False, half=half)
            except Exception as e:
                print("predict failed half=", half, e)
                continue
            boxes = res[0].boxes
            if boxes is None or len(boxes) == 0:
                continue
            if half:
                hits_half += 1
            else:
                hits_full += 1
            names = model.names or {}
            for box in boxes:
                classes.add(str(names.get(int(box.cls[0]), int(box.cls[0]))))
    cap.release()
    print("frames_with_det half", hits_half, "classes", sorted(raw_classes_half))
    print("frames_with_det full", hits_full, "classes", sorted(raw_classes_full))


if __name__ == "__main__":
    main()
