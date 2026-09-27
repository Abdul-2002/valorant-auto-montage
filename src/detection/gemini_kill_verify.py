"""Gemini short-clip visual verifier: accept/reject kill candidates."""

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

log = logging.getLogger(__name__)

_VERIFY_PROMPT = """You are verifying ONE candidate kill moment in a Valorant FIRST-PERSON POV clip.

The clip is centered on a proposed kill timestamp. Decide if this is a REAL player kill
by the person holding the camera (live gameplay POV).

ACCEPT only if ALL are true:
- Live first-person gameplay (not death cam, spectator, scoreboard, agent select, menu)
- The POV player gets an elimination (enemy dies / kill confirm / skull / clear kill)
- Not only a teammate kill in the feed while you are dead/spectating

REJECT if ANY are true:
- Death cam / "KILLED BY" / combat report / SWITCH PLAYER
- Spectator UI
- No elimination occurs in the clip
- Unclear / cannot tell

Return ONLY JSON with this exact schema:
{
  "accept": true,
  "is_live_pov": true,
  "is_player_kill": true,
  "is_death_or_spectator": false,
  "confidence": 0.0,
  "reason": "short explanation"
}
"""

_VERIFY_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "accept": {"type": "BOOLEAN"},
        "is_live_pov": {"type": "BOOLEAN"},
        "is_player_kill": {"type": "BOOLEAN"},
        "is_death_or_spectator": {"type": "BOOLEAN"},
        "confidence": {"type": "NUMBER"},
        "reason": {"type": "STRING"},
    },
    "required": [
        "accept",
        "is_live_pov",
        "is_player_kill",
        "is_death_or_spectator",
        "confidence",
        "reason",
    ],
}


def _ffmpeg_exe() -> str:
    try:
        from src.io.audio_loader import resolve_ffmpeg_exe

        return resolve_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def cut_verify_clip(
    *,
    video_path: Path,
    timestamp_sec: float,
    pre_sec: float,
    post_sec: float,
    out_path: Path,
) -> bool:
    """Cut a short mp4 window around timestamp. Returns True on success."""
    start = max(0.0, float(timestamp_sec) - float(pre_sec))
    dur = float(pre_sec) + float(post_sec)
    cmd = [
        _ffmpeg_exe(),
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(video_path),
        "-t",
        f"{dur:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "28",
        "-an",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception:
        log.exception("gemini_kill_verify: ffmpeg cut failed at %.3fs", timestamp_sec)
        return False
    if proc.returncode != 0 or not out_path.is_file() or out_path.stat().st_size < 1000:
        log.warning(
            "gemini_kill_verify: bad clip at %.3fs rc=%s stderr=%s",
            timestamp_sec,
            proc.returncode,
            (proc.stderr or "")[-400:],
        )
        return False
    return True


def _parse_verify_json(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Best-effort extract object
        a = text.find("{")
        b = text.rfind("}")
        if a < 0 or b <= a:
            return None
        try:
            data = json.loads(text[a : b + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    return data


def _decision_accept(parsed: dict[str, Any], min_confidence: float) -> bool:
    if parsed.get("is_death_or_spectator") is True:
        return False
    if parsed.get("is_live_pov") is False:
        return False
    if parsed.get("is_player_kill") is False:
        return False
    if parsed.get("accept") is not True:
        return False
    try:
        conf = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    return conf >= float(min_confidence)


@register_detector("gemini_kill_verify")
@dataclass
class GeminiKillVerifyDetector(Detector):
    """Upload short clips around candidates; keep only Gemini-accepted player kills."""

    model: str = "gemini-2.5-flash-lite"
    clip_pre_sec: float = 1.0
    clip_post_sec: float = 1.2
    min_confidence: float = 0.55
    generate_timeout_sec: float = 90.0
    poll_timeout_sec: float = 120.0

    def detect(self, ctx: DetectionContext) -> list[dict[str, Any]]:
        candidates: list[dict] = list(ctx.config.get("_candidate_events") or [])
        if not candidates:
            return []

        api_key = (
            ctx.config.get("ai_director", {}).get("gemini", {}).get("api_key", "")
            or os.environ.get("GEMINI_API_KEY", "")
        )
        if not api_key:
            log.warning("gemini_kill_verify: no API key; passing candidates through unverified")
            return list(candidates)

        try:
            from google import genai  # type: ignore
        except Exception:
            log.exception("gemini_kill_verify: google-genai import failed")
            return list(candidates)

        client = genai.Client(api_key=api_key)
        video_path = Path(ctx.video_path)
        out: list[dict[str, Any]] = []
        accepted = 0
        rejected = 0

        with tempfile.TemporaryDirectory(prefix="gemini_kill_verify_") as tmp:
            tmp_dir = Path(tmp)
            for i, cand in enumerate(candidates):
                ts = float(cand.get("timestamp_sec", 0.0))
                clip_path = tmp_dir / f"c{i:03d}_{ts:.3f}.mp4"
                if not cut_verify_clip(
                    video_path=video_path,
                    timestamp_sec=ts,
                    pre_sec=self.clip_pre_sec,
                    post_sec=self.clip_post_sec,
                    out_path=clip_path,
                ):
                    rejected += 1
                    log.warning("gemini_kill_verify: REJECT clip-cut-fail t=%.3f", ts)
                    continue

                verdict = self._verify_clip(client, clip_path)
                if verdict is None:
                    rejected += 1
                    log.warning("gemini_kill_verify: REJECT api-fail t=%.3f", ts)
                    continue

                ok = _decision_accept(verdict, self.min_confidence)
                reason = str(verdict.get("reason", ""))[:200]
                conf = float(verdict.get("confidence", 0.0) or 0.0)
                if ok:
                    accepted += 1
                    out.append(
                        {
                            **cand,
                            "timestamp_sec": ts,
                            "score": max(float(cand.get("score", 0.5)), conf),
                            "source": "gemini_kill_verify",
                            "_verify": verdict,
                            "_original_timestamp_sec": float(
                                cand.get("_original_timestamp_sec", ts)
                            ),
                        }
                    )
                    log.warning(
                        "gemini_kill_verify: ACCEPT t=%.3f conf=%.2f reason=%s",
                        ts,
                        conf,
                        reason,
                    )
                else:
                    rejected += 1
                    log.warning(
                        "gemini_kill_verify: REJECT t=%.3f conf=%.2f reason=%s verdict=%s",
                        ts,
                        conf,
                        reason,
                        {
                            k: verdict.get(k)
                            for k in (
                                "accept",
                                "is_live_pov",
                                "is_player_kill",
                                "is_death_or_spectator",
                            )
                        },
                    )

        log.warning(
            "gemini_kill_verify: kept %d/%d for video %d (rejected=%d)",
            accepted,
            len(candidates),
            ctx.video_index,
            rejected,
        )
        return out

    def _verify_clip(self, client: Any, clip_path: Path) -> dict[str, Any] | None:
        try:
            uploaded = client.files.upload(file=str(clip_path))
        except Exception:
            log.exception("gemini_kill_verify: upload failed %s", clip_path.name)
            return None

        deadline = time.monotonic() + float(self.poll_timeout_sec)
        file_state = uploaded
        while True:
            try:
                file_state = client.files.get(name=uploaded.name)
                state = str(getattr(file_state, "state", "")).upper()
            except Exception:
                log.exception("gemini_kill_verify: poll failed")
                return None
            if "ACTIVE" in state:
                break
            if "FAILED" in state:
                log.warning("gemini_kill_verify: file FAILED")
                return None
            if time.monotonic() > deadline:
                log.warning("gemini_kill_verify: poll timeout")
                return None
            time.sleep(2)

        models = [self.model]
        if self.model != "gemini-2.5-flash-lite":
            models.append("gemini-2.5-flash-lite")

        parsed: dict[str, Any] | None = None
        for model_name in models:
            for attempt in range(1, 5):
                def _call(m: str = model_name) -> Any:
                    return client.models.generate_content(
                        model=m,
                        contents=[file_state, _VERIFY_PROMPT],
                        config={
                            "response_mime_type": "application/json",
                            "response_schema": _VERIFY_SCHEMA,
                        },
                    )

                try:
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        resp = pool.submit(_call).result(
                            timeout=float(self.generate_timeout_sec)
                        )
                    text = getattr(resp, "text", None) or ""
                    parsed = _parse_verify_json(text)
                    if parsed is None:
                        log.warning("gemini_kill_verify: bad JSON from %s: %s", model_name, text[:300])
                    break
                except FuturesTimeout:
                    log.warning("gemini_kill_verify: generate timed out model=%s", model_name)
                    parsed = None
                    break
                except Exception as exc:
                    msg = str(exc).lower()
                    retryable = (
                        "429" in msg
                        or "resource_exhausted" in msg
                        or "quota" in msg
                        or "503" in msg
                        or "unavailable" in msg
                    )
                    if retryable and attempt < 4:
                        wait_s = 10 * attempt
                        log.warning(
                            "gemini_kill_verify: model=%s attempt %d rate-limited; sleep %ds",
                            model_name,
                            attempt,
                            wait_s,
                        )
                        time.sleep(wait_s)
                        continue
                    log.warning(
                        "gemini_kill_verify: model=%s failed: %s",
                        model_name,
                        type(exc).__name__,
                    )
                    parsed = None
                    break
            if parsed is not None:
                break

        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass
        return parsed
