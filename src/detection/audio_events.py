from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.signal import find_peaks

from src.detection.base import DetectionContext, Detector
from src.detection.registry import register_detector
from src.io.ffmpeg import extract_audio_wav_mono

log = logging.getLogger(__name__)


@register_detector("audio_peaks")
class AudioPeaksDetector(Detector):
    def __init__(
        self,
        rms_threshold_percentile: float = 90.0,
        min_peak_distance_sec: float = 0.3,
        use_hpss: bool = True,
    ) -> None:
        self.rms_threshold_percentile = rms_threshold_percentile
        self.min_peak_distance_sec = min_peak_distance_sec
        self.use_hpss = use_hpss

    def detect(self, ctx: DetectionContext) -> list[dict[str, Any]]:
        try:
            import librosa  # optional dependency
        except Exception:
            # Audio detector is optional; missing deps should not break visual detection.
            return []

        tmp_dir = Path(ctx.config.get("tmp_dir", ctx.video_path.parent / "tmp"))
        wav_path = tmp_dir / f"audio_{ctx.video_index}.wav"
        try:
            extract_audio_wav_mono(ctx.video_path, wav_path, sample_rate=44100, timeout_sec=60)
        except Exception:
            # Missing/unsupported audio should not break the pipeline.
            return []

        y, sr = librosa.load(str(wav_path), sr=None, mono=True)
        if y.size == 0:
            return []

        hop_length = 512
        frame_length = 2048

        # HPSS uses librosa.decompose → sklearn in many installs. Mixed NumPy 2 + old
        # numexpr/bottleneck/sklearn wheels often raise here; fall back to full-band RMS.
        y_use = y
        if self.use_hpss:
            try:
                S = librosa.stft(y)
                _, P = librosa.decompose.hpss(S)
                y_p = librosa.istft(P)
                y_use = y_p
            except Exception as exc:
                log.warning(
                    "audio_peaks: HPSS unavailable (%s); using full-band signal. "
                    "Fix env (e.g. numpy<2 + matching numexpr/sklearn) or set use_hpss: false.",
                    exc,
                )
                y_use = y

        rms = librosa.feature.rms(y=y_use, frame_length=frame_length, hop_length=hop_length)[0]
        if rms.size == 0:
            return []

        threshold = float(np.percentile(rms, self.rms_threshold_percentile))
        min_distance_frames = int(round((self.min_peak_distance_sec * sr) / hop_length))
        peaks, props = find_peaks(rms, height=threshold, distance=max(1, min_distance_frames))

        peak_heights = props.get("peak_heights")
        if peak_heights is None:
            peak_heights = rms[peaks] if peaks.size else np.array([])

        max_h = float(np.max(peak_heights)) if len(peak_heights) else 1.0
        events: list[dict[str, Any]] = []
        for p, h in zip(peaks.tolist(), peak_heights.tolist()):
            t = librosa.frames_to_time(p, sr=sr, hop_length=hop_length)
            score = float(h / max_h) if max_h > 0 else 0.0
            events.append(
                {
                    "video_index": ctx.video_index,
                    "timestamp_sec": float(t),
                    "score": float(np.clip(score, 0.0, 1.0)),
                    "event_type": "audio_peak",
                    "source": "audio",
                }
            )

        return events
