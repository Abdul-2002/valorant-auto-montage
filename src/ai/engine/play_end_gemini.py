"""Layer 3: optional Gemini arbiter for residual long post-kill tails.

Only consulted when Layer 1 still leaves more than ``residual_tail_sec`` after the
last kill and no death/round cut fired. Fail-open: any API/parse error keeps the
Layer 1 end.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

import cv2

from src.config.effect_models import PlayEndEffectConfig

logger = logging.getLogger(__name__)

_PROMPT = """You are timing the end of a Valorant highlight clip.
The player's last kill is at source time {last_kill:.2f}s.
Frames below are sampled AFTER that kill.
Return JSON only:
{{"play_end_sec": <float absolute source seconds>, "reason": "<short>"}}
Rules:
- play_end_sec must be >= {last_kill:.2f}
- End as soon as the play is over: player death, spectator/death-cam, round over,
  long idle after the frag, or clear exit from the fight.
- Do NOT include the player's own death screen or post-round lobby.
- Prefer an earlier cut when unsure.
"""


def _encode_jpeg(frame: object, *, max_width: int = 640) -> bytes | None:
    import numpy as np

    arr = np.asarray(frame)
    if arr.ndim != 3:
        return None
    h, w = arr.shape[:2]
    if w > max_width:
        scale = max_width / float(w)
        arr = cv2.resize(arr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", arr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        return None
    return bytes(buf)


def sample_post_kill_jpegs(
    video_path: Path,
    *,
    last_kill_sec: float,
    until_sec: float,
    count: int = 4,
) -> list[bytes]:
    """Evenly sample JPEG frames in (last_kill, until] for the Gemini arbiter."""
    lo = float(last_kill_sec) + 0.15
    hi = float(until_sec)
    if hi <= lo or count < 1:
        return []
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []
    frames: list[bytes] = []
    try:
        for i in range(count):
            t = lo + (hi - lo) * ((i + 1) / (count + 1))
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            encoded = _encode_jpeg(frame)
            if encoded:
                frames.append(encoded)
    finally:
        cap.release()
    return frames


def parse_play_end_response(text: str, *, last_kill_sec: float, until_sec: float) -> float | None:
    """Extract a clamped play_end_sec from model JSON, or None."""
    raw = (text or "").strip()
    if not raw:
        return None
    a, b = raw.find("{"), raw.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        data = json.loads(raw[a : b + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "play_end_sec" not in data:
        return None
    try:
        end = float(data["play_end_sec"])
    except (TypeError, ValueError):
        return None
    lo = float(last_kill_sec) + 0.05
    hi = float(until_sec)
    if end < lo or end > hi + 0.5:
        return None
    return float(min(max(end, lo), hi))


def _default_generate(*, api_key: str, model: str, prompt: str, images: list[bytes]) -> str:
    from google import genai  # type: ignore
    from google.genai import types  # type: ignore

    client = genai.Client(api_key=api_key)
    parts: list[Any] = [types.Part.from_text(text=prompt)]
    for jpeg in images:
        parts.append(types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"))
    resp = client.models.generate_content(
        model=model,
        contents=parts,
        config={"temperature": 0.1, "response_mime_type": "application/json"},
    )
    return str(getattr(resp, "text", "") or "")


def maybe_gemini_play_end(
    *,
    video_path: Path,
    last_kill_sec: float,
    layer1_end_sec: float,
    cfg: PlayEndEffectConfig,
    api_key: str,
    generate: Callable[..., str] | None = None,
    sample_frames: Callable[..., list[bytes]] | None = None,
) -> float | None:
    """Return a tighter end from Gemini, or None to keep Layer 1."""
    if not cfg.gemini_enabled or not api_key:
        return None
    tail = float(layer1_end_sec) - float(last_kill_sec)
    if tail <= float(cfg.residual_tail_sec):
        return None
    sampler = sample_frames or sample_post_kill_jpegs
    images = sampler(video_path, last_kill_sec=float(last_kill_sec), until_sec=float(layer1_end_sec), count=4)
    if len(images) < 2:
        return None
    prompt = _PROMPT.format(last_kill=float(last_kill_sec))
    gen = generate or _default_generate
    try:
        text = gen(api_key=api_key, model=str(cfg.gemini_model), prompt=prompt, images=images)
    except Exception:
        logger.exception("play_end_gemini: generate failed; keeping Layer 1 end")
        return None
    return parse_play_end_response(text, last_kill_sec=float(last_kill_sec), until_sec=float(layer1_end_sec))


def collect_gemini_ends_for_clips(
    clips: list[Any],
    *,
    cfg: PlayEndEffectConfig,
    video_paths: list[Path],
    api_key: str,
    death_finder: Callable[..., float | None] | None = None,
    generate: Callable[..., str] | None = None,
) -> dict[tuple[int, float], float]:
    """Precompute Gemini ends keyed by (video_index, round(last_kill, 3)).

    Only for clips whose Layer-1 recipe cap still yields a long residual tail
    and where a cheap death scan found nothing.
    """
    from src.ai.engine.play_end import find_first_death_sec, recipe_max_post_sec, resolve_play_end_sec

    if not cfg.enabled or not cfg.gemini_enabled or not api_key:
        return {}
    scan = death_finder or find_first_death_sec
    out: dict[tuple[int, float], float] = {}
    for clip in clips:
        vi = int(clip.video_index)
        last_kill = float(clip.kill_timestamp_sec)
        if not (0 <= vi < len(video_paths)):
            continue
        recipe = str(getattr(clip, "recipe", "clean") or "clean")
        cap = recipe_max_post_sec(recipe, cfg)
        death = scan(video_paths[vi], last_kill + 0.05, last_kill + cap, sample_fps=float(cfg.sample_fps))
        layer1 = resolve_play_end_sec(
            last_kill_sec=last_kill,
            recipe=recipe,
            cfg=cfg,
            death_sec=death,
        )
        layer1 = min(layer1, float(clip.end_sec))
        gem = maybe_gemini_play_end(
            video_path=video_paths[vi],
            last_kill_sec=last_kill,
            layer1_end_sec=layer1,
            cfg=cfg,
            api_key=api_key,
            generate=generate,
        )
        if gem is not None:
            out[(vi, round(last_kill, 3))] = float(gem)
    return out
