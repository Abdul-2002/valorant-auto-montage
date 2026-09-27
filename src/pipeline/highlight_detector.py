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

_AUDIO_DETECTORS = frozenset({"audio_peaks"})

# Detector name -> config attribute on DetectionConfig (None = no nested cfg).
_DETECTOR_CFG_ATTR: dict[str, str | None] = {
    "valorant_kill_feed": "valorant_kill_feed",
    "audio_peaks": "audio_peaks",
    "valorant_yolo": "valorant_yolo",
    "auto_gaming_yolo": "auto_gaming_yolo",
    "gemini_video": "gemini_video",
    "gemini_kill_verify": "gemini_kill_verify",
    "hud_ocr": "hud_ocr",
    "kill_frame_refine": None,
}


def _build_ctx(
    idx: int, vp: Path, assets_dir: Path, config: AppConfig, extra: dict | None = None
) -> DetectionContext:
    cfg = config.model_dump(mode="json")
    if extra:
        cfg.update(extra)
    return DetectionContext(
        video_index=idx,
        video_path=vp,
        assets_dir=assets_dir,
        config=cfg,
    )


def _detector_config(det_name: str, config: AppConfig) -> dict | None:
    """Return detector kwargs, or None if the detector is disabled / unknown."""
    attr = _DETECTOR_CFG_ATTR.get(det_name)
    if attr is None:
        return {} if det_name in _DETECTOR_CFG_ATTR else None

    nested = getattr(config.detection, attr, None)
    if nested is None:
        return None
    det_cfg = nested.model_dump(mode="json")
    if "enabled" in det_cfg and not det_cfg.pop("enabled"):
        return None
    return det_cfg


def _run_detector(det_name: str, ctx: DetectionContext, config: AppConfig) -> list[dict]:
    det_cfg = _detector_config(det_name, config)
    if det_cfg is None:
        return []
    det_cls = get_detector(det_name)
    return det_cls.from_config(det_cfg).detect(ctx)


def _run_active_detectors(
    *,
    idx: int,
    vp: Path,
    assets_dir: Path,
    config: AppConfig,
    active: list[str],
) -> tuple[list[dict], list[dict]]:
    """Run listed detectors; split audio vs visual."""
    ctx = _build_ctx(idx, vp, assets_dir, config)
    visual: list[dict] = []
    audio: list[dict] = []
    for det_name in active:
        try:
            events = _run_detector(det_name, ctx, config)
        except Exception:
            log.exception("highlight_detector: detector %s failed for video %d", det_name, idx)
            events = []
        if det_name in _AUDIO_DETECTORS:
            audio.extend(events)
        else:
            visual.extend(events)
    return visual, audio


def _gemini_detection_pipeline(
    *,
    idx: int,
    vp: Path,
    assets_dir: Path,
    config: AppConfig,
) -> tuple[list[dict], list[dict]]:
    """Opt-in Gemini detection path (disabled by default). Prefer auto_gaming YOLO."""
    ctx = _build_ctx(idx, vp, assets_dir, config)
    gemini_events = _run_detector("gemini_video", ctx, config)
    log.warning("highlight_detector: gemini found %d events for video %d", len(gemini_events), idx)

    refined_map: dict[float, float] = {}
    if gemini_events and config.detection.hud_ocr.enabled:
        refined = _run_detector(
            "hud_ocr",
            _build_ctx(idx, vp, assets_dir, config, extra={"_candidate_events": gemini_events}),
            config,
        )
        for r in refined:
            orig_t, new_t = r.get("_original_timestamp_sec"), r.get("timestamp_sec")
            if orig_t is not None and new_t is not None:
                refined_map[float(orig_t)] = float(new_t)

    skull_map: dict[float, float] = {}
    if gemini_events:
        try:
            skull_hits = _run_detector(
                "kill_frame_refine",
                _build_ctx(idx, vp, assets_dir, config, extra={"_candidate_events": gemini_events}),
                config,
            )
        except Exception:
            log.exception("highlight_detector: kill_frame_refine failed for video %d", idx)
            skull_hits = []
        for r in skull_hits:
            orig_t, new_t = r.get("_original_timestamp_sec"), r.get("timestamp_sec")
            if orig_t is not None and new_t is not None:
                skull_map[float(orig_t)] = float(new_t)
                refined_map[float(orig_t)] = float(new_t)

    if skull_map:
        kept: list[dict] = []
        for ev in gemini_events:
            orig_t = float(ev["timestamp_sec"])
            new_t = skull_map.get(orig_t)
            if new_t is None:
                nearest = min(skull_map.keys(), key=lambda k: abs(k - orig_t))
                if abs(nearest - orig_t) <= 0.05:
                    new_t = skull_map[nearest]
            if new_t is None:
                continue
            kept.append({**ev, "timestamp_sec": float(new_t), "source": "kill_frame_refine"})
        gemini_events = kept
    elif gemini_events:
        log.warning(
            "highlight_detector: kill_frame_refine locked 0/%d; clearing gemini for video %d",
            len(gemini_events),
            idx,
        )
        gemini_events = []

    verify_cfg = getattr(config.detection, "gemini_kill_verify", None)
    if gemini_events and verify_cfg is not None and bool(getattr(verify_cfg, "enabled", False)):
        before = len(gemini_events)
        try:
            gemini_events = _run_detector(
                "gemini_kill_verify",
                _build_ctx(idx, vp, assets_dir, config, extra={"_candidate_events": gemini_events}),
                config,
            )
        except Exception:
            log.exception("highlight_detector: gemini_kill_verify failed for video %d", idx)
        log.warning(
            "highlight_detector: gemini_kill_verify kept %d/%d for video %d",
            len(gemini_events),
            before,
            idx,
        )

    visual: list[dict] = []
    if not gemini_events:
        log.warning("highlight_detector: gemini empty for video %d; falling back to auto_gaming_yolo", idx)
        visual.extend(_run_detector("auto_gaming_yolo", ctx, config))
    else:
        try:
            import cv2

            cap = cv2.VideoCapture(str(vp))
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            nframes = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
            cap.release()
            dur = (nframes / fps) if fps > 1e-3 else 0.0
        except Exception:
            dur = 0.0
        stamps = sorted(float(e["timestamp_sec"]) for e in gemini_events)
        span = stamps[-1] - stamps[0] if len(stamps) >= 2 else 0.0
        collapsed = dur >= 60.0 and stamps[-1] <= max(12.0, dur * 0.08) and span <= 8.0
        if collapsed:
            log.warning(
                "highlight_detector: gemini timestamps collapsed; falling back to auto_gaming_yolo (video %d)",
                idx,
            )
            visual.extend(_run_detector("auto_gaming_yolo", ctx, config))
        else:
            visual.extend(gemini_events)

    audio = _run_detector("audio_peaks", _build_ctx(idx, vp, assets_dir, config), config)
    return visual, audio


def detect_highlights(
    *,
    video_paths: list[Path],
    config: AppConfig,
    task_progress_cb: Callable[[float], None] | None = None,
) -> list[DetectedEvent]:
    """Detect kills for montage assembly.

    Default: local auto_gaming YOLO (see detection.strategy / active_detectors).
    Gemini is used only by the AI director for effect recipes, not here, unless
    strategy is explicitly set to \"gemini\".
    """
    assets_dir = (Path(__file__).resolve().parents[2] / "assets").resolve()
    strategy = str(getattr(config.detection, "strategy", "yolo_legacy"))

    if task_progress_cb:
        task_progress_cb(0.2)

    all_visual: list[dict] = []
    all_audio: list[dict] = []

    for idx, vp in enumerate(video_paths):
        if strategy == "gemini":
            visual, audio = _gemini_detection_pipeline(
                idx=idx, vp=vp, assets_dir=assets_dir, config=config
            )
        else:
            # yolo_legacy / hybrid: run whatever is listed in active_detectors.
            visual, audio = _run_active_detectors(
                idx=idx,
                vp=vp,
                assets_dir=assets_dir,
                config=config,
                active=list(config.detection.active_detectors),
            )
        all_visual.extend(visual)
        all_audio.extend(audio)

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
