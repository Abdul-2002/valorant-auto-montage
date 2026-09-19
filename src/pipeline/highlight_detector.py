from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from src.config.models import AppConfig
from src.detection.base import DetectionContext
from src.detection.event_scorer import ScoringWeights, score_and_merge
from src.detection.registry import get_detector
from src.pipeline.types import DetectedEvent

log = logging.getLogger(__name__)


def _build_ctx(idx: int, vp: Path, assets_dir: Path, config: AppConfig, extra: dict | None = None) -> DetectionContext:
    cfg = config.model_dump(mode="json")
    if extra:
        cfg.update(extra)
    return DetectionContext(
        video_index=idx,
        video_path=vp,
        assets_dir=assets_dir,
        config=cfg,
    )


def _run_detector(det_name: str, ctx: DetectionContext, config: AppConfig) -> list[dict]:
    """Get the detector class, build its config dict, and run detection."""
    det_cls = get_detector(det_name)
    det_cfg: dict = {}

    if det_name == "valorant_kill_feed":
        det_cfg = config.detection.valorant_kill_feed.model_dump(mode="json")
    elif det_name == "audio_peaks":
        det_cfg = config.detection.audio_peaks.model_dump(mode="json")
    elif det_name == "valorant_yolo":
        if not config.detection.valorant_yolo.enabled:
            return []
        det_cfg = config.detection.valorant_yolo.model_dump(mode="json")
        det_cfg.pop("enabled", None)
    elif det_name == "auto_gaming_yolo":
        if not config.detection.auto_gaming_yolo.enabled:
            return []
        det_cfg = config.detection.auto_gaming_yolo.model_dump(mode="json")
        det_cfg.pop("enabled", None)
    elif det_name == "gemini_video":
        if not config.detection.gemini_video.enabled:
            return []
        det_cfg = config.detection.gemini_video.model_dump(mode="json")
        det_cfg.pop("enabled", None)
    elif det_name == "hud_ocr":
        if not config.detection.hud_ocr.enabled:
            return []
        det_cfg = config.detection.hud_ocr.model_dump(mode="json")
        det_cfg.pop("enabled", None)

    det = det_cls.from_config(det_cfg)
    return det.detect(ctx)


def detect_highlights(
    *,
    video_paths: list[Path],
    config: AppConfig,
    task_progress_cb: Callable[[float], None] | None = None,
) -> list[DetectedEvent]:
    assets_dir = (Path(__file__).resolve().parents[2] / "assets").resolve()
    strategy = str(getattr(config.detection, "strategy", "gemini"))

    if task_progress_cb:
        task_progress_cb(0.2)

    all_visual: list[dict] = []
    all_audio: list[dict] = []

    for idx, vp in enumerate(video_paths):
        if strategy == "yolo_legacy":
            # Original YOLO + audio_peaks behavior preserved exactly.
            ctx = _build_ctx(idx, vp, assets_dir, config)
            active = config.detection.active_detectors
            for det_name in active:
                events = _run_detector(det_name, ctx, config)
                if det_name in ("audio_peaks",):
                    all_audio.extend(events)
                else:
                    all_visual.extend(events)

        elif strategy == "gemini":
            # Step 1: Gemini semantic detection.
            ctx = _build_ctx(idx, vp, assets_dir, config)
            gemini_events = _run_detector("gemini_video", ctx, config)
            log.warning("highlight_detector: gemini found %d events for video %d", len(gemini_events), idx)

            # Step 2: HUD OCR refines Gemini timestamps to exact frames.
            # Pass candidate events so HUD OCR only scans around those timestamps.
            if gemini_events and config.detection.hud_ocr.enabled:
                ctx_with_candidates = _build_ctx(
                    idx, vp, assets_dir, config,
                    extra={"_candidate_events": gemini_events},
                )
                refined = _run_detector("hud_ocr", ctx_with_candidates, config)
                # Build a refined timestamp map keyed by original timestamp.
                refined_map: dict[float, float] = {}
                for r in refined:
                    orig_t = r.get("_original_timestamp_sec")
                    new_t = r.get("timestamp_sec")
                    if orig_t is not None and new_t is not None:
                        refined_map[float(orig_t)] = float(new_t)

                # Apply refinements to gemini events.
                for i, ev in enumerate(gemini_events):
                    orig_t = float(ev["timestamp_sec"])
                    if orig_t in refined_map:
                        gemini_events[i] = {**ev, "timestamp_sec": refined_map[orig_t]}
                        log.warning(
                            "highlight_detector: HUD OCR refined %.3fs -> %.3fs for video %d",
                            orig_t, refined_map[orig_t], idx,
                        )

            all_visual.extend(gemini_events)

            # Step 3: Audio peaks as secondary confirmation signal.
            ctx_audio = _build_ctx(idx, vp, assets_dir, config)
            audio_events = _run_detector("audio_peaks", ctx_audio, config)
            all_audio.extend(audio_events)

        else:  # "hybrid" -- run all active detectors.
            ctx = _build_ctx(idx, vp, assets_dir, config)
            for det_name in config.detection.active_detectors:
                try:
                    events = _run_detector(det_name, ctx, config)
                except Exception:
                    log.exception("highlight_detector: detector %s failed for video %d", det_name, idx)
                    events = []
                if det_name in ("audio_peaks",):
                    all_audio.extend(events)
                else:
                    all_visual.extend(events)

        if task_progress_cb:
            task_progress_cb(0.2 + 0.6 * ((idx + 1) / max(1, len(video_paths))))

    weights = ScoringWeights(
        visual_weight=config.detection.scoring.visual_weight,
        audio_weight=config.detection.scoring.audio_weight,
        dedup_window_sec=config.detection.scoring.dedup_window_sec,
    )
    highlights = score_and_merge(visual_events=all_visual, audio_events=all_audio, weights=weights)

    if task_progress_cb:
        task_progress_cb(0.95)
    return highlights
