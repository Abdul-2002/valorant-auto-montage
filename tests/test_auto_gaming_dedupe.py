"""Unit tests for auto_gaming kill-1/kill-2 duplicate collapse."""

from __future__ import annotations

from src.detection.auto_gaming_yolo import dedupe_kill_detections


def _kill(ts: float, score: float = 0.9, video_index: int = 0, raw: str = "kill-1") -> dict:
    return {
        "video_index": video_index,
        "timestamp_sec": ts,
        "score": score,
        "event_type": "kill",
        "source": "auto_gaming_yolo",
        "raw_class": raw,
    }


def test_dedupe_collapses_kill1_kill2_flicker() -> None:
    # Same frag: kill-1 then kill-2 ~0.3s later (bake-off duplicate pattern).
    raw = [
        _kill(10.0, score=0.85, raw="kill-1"),
        _kill(10.32, score=0.92, raw="kill-2"),
        _kill(14.0, score=0.88, raw="kill-1"),
    ]
    out = dedupe_kill_detections(raw, gap_sec=1.0)
    assert len(out) == 2
    assert abs(out[0]["timestamp_sec"] - 10.32) < 1e-6
    assert out[0]["score"] == 0.92
    assert abs(out[1]["timestamp_sec"] - 14.0) < 1e-6


def test_dedupe_keeps_separate_frags() -> None:
    raw = [
        _kill(10.0, score=0.9, raw="kill-1"),
        _kill(11.5, score=0.9, raw="kill-2"),
    ]
    out = dedupe_kill_detections(raw, gap_sec=1.0)
    assert len(out) == 2


def test_dedupe_disabled_when_gap_zero() -> None:
    raw = [_kill(10.0), _kill(10.2, raw="kill-2")]
    out = dedupe_kill_detections(raw, gap_sec=0.0)
    assert len(out) == 2


def test_dedupe_is_per_video() -> None:
    raw = [
        _kill(10.0, video_index=0),
        _kill(10.2, video_index=1, raw="kill-2"),
    ]
    out = dedupe_kill_detections(raw, gap_sec=1.0)
    assert len(out) == 2


def test_default_config_uses_auto_gaming_not_gemini_detection() -> None:
    from src.config.models import AppConfig

    cfg = AppConfig()
    assert cfg.detection.strategy == "yolo_legacy"
    assert cfg.detection.active_detectors == ["auto_gaming_yolo"]
    assert cfg.detection.gemini_video.enabled is False
    assert cfg.detection.gemini_kill_verify.enabled is False
    assert cfg.detection.auto_gaming_yolo.enabled is True
    assert cfg.detection.auto_gaming_yolo.kill_dedupe_gap_sec == 1.0
    assert cfg.ai_director.provider == "gemini"
