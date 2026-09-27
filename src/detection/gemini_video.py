from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.detection.base import DetectionContext, Detector
from src.detection.registry import register_detector

# Hard ceiling so a hung Files/Generate call cannot stall the whole montage run.
_GENERATE_TIMEOUT_SEC = 180.0

log = logging.getLogger(__name__)

# Gemini Files API hard limit is 2 GiB. Stay under with margin.
_MAX_UPLOAD_BYTES = 1_900_000_000

_DETECTION_PROMPT = """Analyze this Valorant gameplay video. Find every kill, multi-kill, clutch, and ace moment.

Return ONLY valid JSON with this exact structure:
{"events": [{"timestamp_sec": 123.5, "event_type": "kill", "description": "headshot with Vandal", "excitement": 0.7}]}

Rules:
- timestamp_sec: seconds into the video when the kill happens (float)
- event_type: one of "kill", "double_kill", "triple_kill", "quadra_kill", "ace", "clutch"
- excitement: 0.0 to 1.0 (how montage-worthy is this moment)
- Only include actual gameplay kills. Ignore menus, loading screens, agent select.
- Include ALL kills you can identify, even low-excitement ones.
- Prefer the exact moment of elimination (body drop / kill confirm), not the later killfeed UI."""

# Excitement score multipliers by event type (used to boost higher-value events).
_EVENT_SCORE_BOOST: dict[str, float] = {
    "kill": 1.0,
    "double_kill": 1.2,
    "triple_kill": 1.4,
    "quadra_kill": 1.6,
    "ace": 1.8,
    "clutch": 1.7,
}


def _make_detection_proxy(src: Path) -> Path | None:
    """Re-encode oversized VODs for Gemini upload. Timeline length stays the same."""
    try:
        from src.io.audio_loader import resolve_ffmpeg_exe

        ffmpeg = resolve_ffmpeg_exe()
    except Exception:
        ffmpeg = "ffmpeg"

    out = Path(tempfile.gettempdir()) / f"gemini_proxy_{src.stem[:40]}.mp4"
    if (
        out.is_file()
        and out.stat().st_size < _MAX_UPLOAD_BYTES
        and out.stat().st_mtime >= src.stat().st_mtime
    ):
        log.warning("gemini_video: reusing detection proxy %s", out)
        return out

    base_cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(src),
        "-vf",
        "scale=1280:-2",
        "-r",
        "30",
        "-an",
    ]
    nvenc_cmd = base_cmd + ["-c:v", "h264_nvenc", "-preset", "p4", "-b:v", "2500k", str(out)]
    log.warning("gemini_video: building detection proxy for oversized source (%s)...", src.name)
    try:
        subprocess.run(nvenc_cmd, check=True, capture_output=True)
    except Exception:
        x264_cmd = base_cmd + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", str(out)]
        try:
            subprocess.run(x264_cmd, check=True, capture_output=True)
        except Exception:
            log.exception("gemini_video: failed to build detection proxy")
            return None

    if not out.is_file() or out.stat().st_size <= 0:
        return None
    log.warning(
        "gemini_video: proxy ready size=%.1fMB path=%s",
        out.stat().st_size / 1e6,
        out,
    )
    return out


def _upload_path_for(src: Path) -> tuple[Path, Path | None]:
    """Return (path_to_upload, temp_proxy_or_none)."""
    try:
        size = src.stat().st_size
    except OSError:
        return src, None
    if size <= _MAX_UPLOAD_BYTES:
        return src, None
    proxy = _make_detection_proxy(src)
    if proxy is None:
        return src, None
    return proxy, proxy


@register_detector("gemini_video")
@dataclass
class GeminiVideoDetector(Detector):
    """
    Primary detector: uses Gemini 2.5 Flash video understanding to identify
    kills, multi-kills, clutches, and aces with semantic understanding.

    Uploads the video once to the Gemini Files API and sends a structured
    prompt. Oversized sources are proxied (same timeline) before upload.
    """

    model: str = "gemini-2.5-flash"
    min_excitement: float = 0.3

    def detect(self, ctx: DetectionContext) -> list[dict[str, Any]]:
        api_key = (
            ctx.config.get("ai_director", {}).get("gemini", {}).get("api_key", "")
            or os.environ.get("GEMINI_API_KEY", "")
        )
        if not api_key:
            log.warning(
                "gemini_video: no API key found. Set GEMINI_API_KEY or ai_director.gemini.api_key in config."
            )
            return []

        try:
            from google import genai  # type: ignore
        except Exception:
            log.exception("gemini_video: failed to import google-genai. Install google-genai package.")
            return []

        client = genai.Client(api_key=api_key)
        src = Path(ctx.video_path)
        upload_path, proxy = _upload_path_for(src)

        log.warning("gemini_video: uploading video %s (this may take a minute)...", upload_path)
        try:
            uploaded = client.files.upload(file=str(upload_path))
        except Exception:
            log.exception("gemini_video: failed to upload video %s", upload_path)
            return []

        deadline = time.monotonic() + 300.0
        while True:
            try:
                file_state = client.files.get(name=uploaded.name)
                state = str(getattr(file_state, "state", "")).upper()
            except Exception:
                log.exception("gemini_video: failed to poll file state")
                return []

            if "ACTIVE" in state:
                break
            if "FAILED" in state:
                log.warning("gemini_video: file processing failed (state=%s)", state)
                return []
            if time.monotonic() > deadline:
                log.warning("gemini_video: timed out waiting for file to become ACTIVE")
                return []

            log.warning("gemini_video: waiting for file to be ACTIVE (state=%s)...", state)
            time.sleep(5)

        log.warning("gemini_video: file ACTIVE, sending detection prompt...")

        models_to_try = [self.model]
        if self.model != "gemini-2.5-flash-lite":
            models_to_try.append("gemini-2.5-flash-lite")

        resp = None
        used_model = self.model
        for model_name in models_to_try:
            used_model = model_name
            for attempt in range(1, 5):
                try:
                    def _call(m: str = model_name):
                        return client.models.generate_content(
                            model=m,
                            contents=[file_state, _DETECTION_PROMPT],
                            config={
                                "response_mime_type": "application/json",
                            },
                        )

                    with ThreadPoolExecutor(max_workers=1) as pool:
                        fut = pool.submit(_call)
                        resp = fut.result(timeout=_GENERATE_TIMEOUT_SEC)
                    break
                except FuturesTimeout:
                    log.warning(
                        "gemini_video: model=%s generate_content timed out after %.0fs (attempt %d)",
                        model_name,
                        _GENERATE_TIMEOUT_SEC,
                        attempt,
                    )
                    resp = None
                    if attempt >= 4:
                        break
                    time.sleep(5)
                except Exception as exc:
                    msg = str(exc).lower()
                    retryable = "503" in msg or "unavailable" in msg or "high demand" in msg
                    if not retryable or attempt >= 4:
                        log.warning(
                            "gemini_video: model=%s failed after %d attempt(s): %s",
                            model_name,
                            attempt,
                            type(exc).__name__,
                        )
                        resp = None
                        break
                    wait_s = 10 * attempt
                    log.warning(
                        "gemini_video: model=%s attempt %d hit demand limit; retry in %ds",
                        model_name,
                        attempt,
                        wait_s,
                    )
                    time.sleep(wait_s)
            if resp is not None:
                break

        if resp is None:
            log.exception("gemini_video: failed to call generate_content on all models")
            return []

        text = getattr(resp, "text", None)
        if not text:
            log.warning("gemini_video: empty response from model=%s", self.model)
            return []

        preview = text[:2000] + "... (truncated)" if len(text) > 2000 else text
        log.warning("gemini_video raw response:\n%s", preview)

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            import re

            m = re.search(r"\{.*\}", text, re.DOTALL)
            if not m:
                log.warning("gemini_video: could not parse JSON from response")
                return []
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                log.warning("gemini_video: could not parse extracted JSON")
                return []

        raw_events = parsed.get("events", [])
        if not isinstance(raw_events, list):
            log.warning("gemini_video: 'events' is not a list in response")
            return []

        events: list[dict[str, Any]] = []
        for e in raw_events:
            if not isinstance(e, dict):
                continue
            ts = e.get("timestamp_sec")
            excitement = float(e.get("excitement", 0.5))
            event_type = str(e.get("event_type", "kill")).lower().replace(" ", "_")
            description = e.get("description")

            if ts is None:
                continue
            try:
                ts = float(ts)
            except (TypeError, ValueError):
                continue

            if excitement < self.min_excitement:
                continue

            boost = _EVENT_SCORE_BOOST.get(event_type, 1.0)
            score = min(1.0, excitement * boost)

            events.append(
                {
                    "video_index": ctx.video_index,
                    "timestamp_sec": ts,
                    "score": float(score),
                    "event_type": event_type,
                    "source": "gemini_video",
                    "meta": {
                        "description": str(description) if description is not None else "",
                        "tags": [event_type],
                        "source": "gemini_video",
                        "upload_proxy": bool(proxy is not None),
                    },
                }
            )

        log.warning(
            "gemini_video: found %d events (min_excitement=%.2f, model=%s)",
            len(events),
            self.min_excitement,
            used_model,
        )

        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass

        return events
