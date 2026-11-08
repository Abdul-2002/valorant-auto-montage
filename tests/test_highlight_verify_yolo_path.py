"""YOLO path must run gemini_kill_verify when enabled (Layer B)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.config.models import AppConfig, GeminiKillVerifyConfig
from src.pipeline.highlight_detector import _run_active_detectors, _verify_kill_candidates


def test_verify_passthrough_when_disabled() -> None:
    cfg = AppConfig()
    cfg.detection.gemini_kill_verify = GeminiKillVerifyConfig(enabled=False)
    cands = [{"timestamp_sec": 1.0, "score": 0.9, "event_type": "kill", "video_index": 0}]
    out = _verify_kill_candidates(
        idx=0,
        vp=Path("fake.mp4"),
        assets_dir=Path("."),
        config=cfg,
        candidates=cands,
    )
    assert out == cands


def test_run_active_detectors_verifies_yolo_candidates() -> None:
    cfg = AppConfig()
    cfg.detection.gemini_kill_verify = GeminiKillVerifyConfig(enabled=True)
    yolo_events = [
        {"timestamp_sec": 1.0, "score": 0.9, "event_type": "kill", "video_index": 0},
        {"timestamp_sec": 2.0, "score": 0.8, "event_type": "kill", "video_index": 0},
    ]
    verified = [yolo_events[0]]

    def fake_run(det_name: str, ctx, config):  # noqa: ANN001
        if det_name == "auto_gaming_yolo":
            return list(yolo_events)
        if det_name == "audio_peaks":
            return []
        if det_name == "gemini_kill_verify":
            assert ctx.config.get("_candidate_events") == yolo_events
            return list(verified)
        return []

    with patch("src.pipeline.highlight_detector._run_detector", side_effect=fake_run):
        visual, audio = _run_active_detectors(
            idx=0,
            vp=Path("fake.mp4"),
            assets_dir=Path("."),
            config=cfg,
            active=["auto_gaming_yolo", "audio_peaks"],
        )
    assert visual == verified
    assert audio == []


def test_default_yaml_enables_verify_and_sam_variant() -> None:
    from src.config import load_config
    from src.config.models import DetectionConfig

    cfg = load_config("config/default.yaml")
    assert cfg.detection.gemini_kill_verify.enabled is True
    assert cfg.detection.sam_variant == "large"
    assert cfg.detection.sam_model_path.endswith("sam2.1_l.pt")
    assert cfg.detection.auto_gaming_yolo.region[0] >= 0.5
    base = DetectionConfig(sam_variant="base")
    assert base.sam_model_path.endswith("sam2.1_b.pt")
    # Disk fallback may resolve to base while large weights are missing.
    resolved = cfg.detection.resolved_sam_model_path()
    assert resolved.endswith(("sam2.1_l.pt", "sam2.1_b.pt", "sam2.1_t.pt"))
