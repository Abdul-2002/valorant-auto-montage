from pathlib import Path
import cv2
from ultralytics import YOLO

video = Path("/videos/Valorant 2026.10.20 - 14.55.33.15.DVR.mp4")
model = YOLO("/app/models/auto_gaming_valorant.pt")
cap = cv2.VideoCapture(str(video))
fps = cap.get(cv2.CAP_PROP_FPS) or 60
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
print("video", video.name, "fps", fps, "frames", n, "sec", n / fps if fps else 0)
hits = 0
kill_hits = 0
for i in range(0, n, max(1, int(fps))):
    cap.set(cv2.CAP_PROP_POS_FRAMES, float(i))
    ok, frame = cap.read()
    if not ok:
        break
    res = model.predict(frame, conf=0.3, verbose=False, half=False)
    boxes = res[0].boxes
    if boxes is None or len(boxes) == 0:
        continue
    hits += 1
    names = model.names or {}
    for box in boxes:
        name = str(names.get(int(box.cls[0]), ""))
        if name.startswith("kill"):
            kill_hits += 1
            break
cap.release()
print("sampled_frames_with_any", hits, "with_kill", kill_hits)
