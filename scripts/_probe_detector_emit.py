"""Confirm AutoGamingYoloDetector emits kills after threshold fix."""
from pathlib import Path

from src.config.models import AppConfig
from src.detection.auto_gaming_yolo import AutoGamingYoloDetector
from src.detection.base import DetectionContext

video = sorted(
    [p for p in Path("/videos").glob("*.mp4") if 300_000_000 < p.stat().st_size < 400_000_000],
    key=lambda p: p.stat().st_size,
)[0]
cfg = AppConfig()
det_cfg = cfg.detection.auto_gaming_yolo.model_dump(mode="json")
det_cfg.pop("enabled", None)
print("conf", det_cfg["confidence_threshold"], "fps", det_cfg["sample_fps"])
det = AutoGamingYoloDetector.from_config(det_cfg)
ctx = DetectionContext(video_index=0, video_path=video, assets_dir=Path("/app/assets"), config={})
print("video", video.name)
events = det.detect(ctx)
print("events", len(events))
print("sample", events[:3])
