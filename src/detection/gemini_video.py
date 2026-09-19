from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from src.detection.base import DetectionContext, Detector
from src.detection.registry import register_detector

log = logging.getLogger(__name__)

_DETECTION_PROMPT = """Analyze this Valorant gameplay video. Find every kill, multi-kill, clutch, and ace moment.

Return ONLY valid JSON with this exact structure:
{"events": [{"timestamp_sec": 123.5, "event_type": "kill", "description": "headshot with Vandal", "excitement": 0.7}]}

Rules:
- timestamp_sec: seconds into the video when the kill happens (float)
- event_type: one of "kill", "double_kill", "triple_kill", "quadra_kill", "ace", "clutch"
- excitement: 0.0 to 1.0 (how montage-worthy is this moment)
- Only include actual gameplay kills. Ignore menus, loading screens, agent select.
- Include ALL kills you can identify, even low-excitement ones."""

# Excitement score multipliers by event type (used to boost higher-value events).
_EVENT_SCORE_BOOST: dict[str, float] = {
    "kill": 1.0,
    "double_kill": 1.2,
    "triple_kill": 1.4,
    "quadra_kill": 1.6,
    "ace": 1.8,
    "clutch": 1.7,
}


@register_detector("gemini_video")
@dataclass
class GeminiVideoDetector(Detector):
    """
    Primary detector: uses Gemini 2.5 Flash video understanding to identify
    kills, multi-kills, clutches, and aces with semantic understanding.

    Uploads the video once to the Gemini Files API and sends a structured
    prompt. Returns 30-50 events from a 20-minute video vs ~14 from YOLO.
    """

    model: str = "gemini-2.5-flash"
    min_excitement: float = 0.3

    def detect(self, ctx: DetectionContext) -> list[dict[str, Any]]:
        # Resolve API key: config > env.
        api_key = (
            ctx.config.get("ai_director", {}).get("gemini", {}).get("api_key", "")
            or os.environ.get("GEMINI_API_KEY", "")
        )
        if not api_key:
            log.warning("gemini_video: no API key found. Set GEMINI_API_KEY or ai_director.gemini.api_key in config.")
            return []

        # Lazy import to avoid hard dependency when Gemini is not used.
        try:
            from google import genai  # type: ignore
        except Exception:
            log.exception("gemini_video: failed to import google-genai. Install google-genai package.")
            return []

        client = genai.Client(api_key=api_key)

        # Upload video via Files API.
        log.warning("gemini_video: uploading video %s (this may take a minute)...", ctx.video_path)
        try:
            uploaded = client.files.upload(file=str(ctx.video_path))
        except Exception:
            log.exception("gemini_video: failed to upload video %s", ctx.video_path)
            return []

        # Poll until the file is ACTIVE (processing completed).
        deadline = time.monotonic() + 300.0  # 5 minute upload timeout
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

        # Send detection prompt.
        try:
            resp = client.models.generate_content(
                model=self.model,
                contents=[file_state, _DETECTION_PROMPT],
                config={
                    "response_mime_type": "application/json",
                },
            )
        except Exception:
            log.exception("gemini_video: failed to call generate_content")
            return []

        text = getattr(resp, "text", None)
        if not text:
            log.warning("gemini_video: empty response from model=%s", self.model)
            return []

        preview = text[:2000] + "... (truncated)" if len(text) > 2000 else text
        log.warning("gemini_video raw response:\n%s", preview)

        # Parse JSON response.
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON from the response if it has surrounding text.
            import re
            m = re.search(r'\{.*\}', text, re.DOTALL)
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

            # Boost score by event type (ace > clutch > triple > double > kill).
            boost = _EVENT_SCORE_BOOST.get(event_type, 1.0)
            score = min(1.0, excitement * boost)

            events.append({
                "video_index": ctx.video_index,
                "timestamp_sec": ts,
                "score": float(score),
                "event_type": event_type,
                "source": "gemini_video",
                "meta": {
                    "description": str(description) if description is not None else "",
                    "tags": [event_type],
                    "source": "gemini_video",
                },
            })

        log.warning(
            "gemini_video: found %d events (min_excitement=%.2f, model=%s)",
            len(events), self.min_excitement, self.model,
        )

        # Clean up: delete the uploaded file to avoid storage costs.
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass  # Non-critical.

        return events
