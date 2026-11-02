"""Gemini labels for YOLO kill plays (ace / clutch / headshot / …).

YOLO owns timestamps. Gemini only classifies short clips cut around each play.
Labels are cached on disk and must feed clip selection (not only the brief).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Sequence

from src.ai.engine.kill_grouping import PLAY_LABEL_RANK, KillGroup
from src.ai.enrichment import EnrichedEvent
from src.io.audio_loader import resolve_ffmpeg_exe

log = logging.getLogger(__name__)

PLAY_LABELS = frozenset(PLAY_LABEL_RANK.keys())
# Flash-lite free tier is tiny (20/day); labeling must not inherit that default.
_DEFAULT_LABEL_MODEL = "gemini-2.5-flash"
_INLINE_MAX_BYTES = 18 * 1024 * 1024
_REQUEST_GAP_SEC = 1.25



def play_cache_key(group: KillGroup) -> str:
    kills = ",".join(f"{t:.2f}" for t in group.kill_secs)
    return f"{group.video_index}:{kills}"


def _cut_span(video: Path, start_sec: float, end_sec: float, out: Path, *, pad: float = 1.2) -> bool:
    start = max(0.0, float(start_sec) - pad)
    dur = max(1.5, float(end_sec) - float(start_sec) + 2.0 * pad)
    ffmpeg = resolve_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(video),
        "-t",
        f"{dur:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-an",
        str(out),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
        return out.is_file() and out.stat().st_size > 1000
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        log.warning("play_labels: ffmpeg cut failed: %s", exc)
        return False


def _load_cache(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in (raw.get("labels") or raw or {}).items() if str(v) in PLAY_LABELS}
    except (OSError, json.JSONDecodeError, TypeError, AttributeError) as exc:
        log.warning("play_labels: cache unreadable (%s)", exc)
        return {}


def _save_cache(path: Path | None, labels: dict[str, str]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"labels": labels}, indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("play_labels: cache write failed (%s)", exc)


def _parse_label(text: str) -> str:
    word = (text or "").strip().lower().split()[0] if (text or "").strip() else ""
    word = "".join(ch for ch in word if ch.isalpha())
    return word if word in PLAY_LABELS else ""


def _wait_file_active(client: object, uploaded: object, *, timeout_sec: float = 90.0) -> object:
    """Poll Files API until video processing reaches ACTIVE (or raise)."""
    deadline = time.time() + float(timeout_sec)
    current = uploaded
    while time.time() < deadline:
        state = getattr(getattr(current, "state", None), "name", None) or str(getattr(current, "state", "") or "")
        if state == "ACTIVE":
            return current
        if state == "FAILED":
            raise RuntimeError(f"Gemini file processing failed: {getattr(current, 'error', None)}")
        time.sleep(2.0)
        current = client.files.get(name=current.name)  # type: ignore[attr-defined]
    raise TimeoutError(f"Gemini file not ACTIVE within {timeout_sec:.0f}s")


def _classify_clip(client: object, model: str, clip: Path, prompt: str) -> str:
    """Prefer inline bytes for short clips; fall back to Files API with ACTIVE wait."""
    from google.genai import types

    data = clip.read_bytes()
    if len(data) <= _INLINE_MAX_BYTES:
        resp = client.models.generate_content(  # type: ignore[attr-defined]
            model=model,
            contents=[
                types.Content(
                    parts=[
                        types.Part.from_bytes(data=data, mime_type="video/mp4"),
                        types.Part(text=prompt),
                    ]
                )
            ],
        )
        return _parse_label(getattr(resp, "text", None) or "")

    uploaded = client.files.upload(file=str(clip))  # type: ignore[attr-defined]
    ready = _wait_file_active(client, uploaded)
    resp = client.models.generate_content(model=model, contents=[ready, prompt])  # type: ignore[attr-defined]
    return _parse_label(getattr(resp, "text", None) or "")


def label_play_groups(
    groups: Sequence[KillGroup],
    *,
    video_paths: list[Path],
    api_key: str,
    model: str = _DEFAULT_LABEL_MODEL,
    cache_path: Path | None = None,
    max_clips: int | None = None,
    pad_sec: float = 1.2,
) -> list[KillGroup]:
    """Attach a Gemini play_label to each KillGroup (cached). Failures leave label empty."""
    key = os.environ.get("GEMINI_API_KEY", "") or api_key
    if not key:
        log.warning("play_labels: no GEMINI_API_KEY; skipping")
        return list(groups)

    # Never use flash-lite for labeling — free-tier RPD is too low for a montage run.
    use_model = str(model or _DEFAULT_LABEL_MODEL)
    if "flash-lite" in use_model.lower():
        log.warning("play_labels: overriding %s -> %s", use_model, _DEFAULT_LABEL_MODEL)
        use_model = _DEFAULT_LABEL_MODEL

    cache = _load_cache(cache_path)
    out: list[KillGroup] = []
    pending: list[tuple[int, KillGroup, str]] = []
    for i, g in enumerate(groups):
        ck = play_cache_key(g)
        cached = cache.get(ck, "")
        if cached in PLAY_LABELS and cached:
            out.append(KillGroup(events=g.events, play_label=cached))
        else:
            out.append(g)
            pending.append((i, g, ck))

    # Prefer multi-kills, then higher detector scores.
    pending.sort(key=lambda t: (len(t[1].events), t[1].score), reverse=True)
    if max_clips is not None:
        pending = pending[: int(max_clips)]

    if not pending:
        return out

    try:
        from google import genai
    except Exception:
        log.exception("play_labels: google-genai unavailable")
        return out

    client = genai.Client(api_key=key)
    prompt = (
        "You are labeling a Valorant gameplay clip for a kill montage. "
        "Watch the killfeed and the frags. Reply with ONE word only from: "
        "ace, clutch, headshot, op, multi, clean, junk. "
        "ace=five kills in one round by the recorder; "
        "clutch=last-alive / low-hp round win feel; "
        "headshot=clear headshot (skull icon or obvious HS); "
        "op=Operator/Marshal sniper highlight; "
        "multi=2–4 kill streak that is not an ace; "
        "clean=solid single kill worth keeping; "
        "junk=miss / team kill / spectator / not a good montage clip."
    )

    with tempfile.TemporaryDirectory(prefix="play_labels_") as tmp:
        tmp_path = Path(tmp)
        for n, (i, g, ck) in enumerate(pending):
            if not 0 <= g.video_index < len(video_paths):
                continue
            vpath = video_paths[g.video_index]
            clip = tmp_path / f"play_{i}.mp4"
            if not _cut_span(vpath, g.kill_secs[0], g.kill_secs[-1], clip, pad=pad_sec):
                continue
            try:
                if n:
                    time.sleep(_REQUEST_GAP_SEC)
                label = _classify_clip(client, use_model, clip, prompt)
                if not label:
                    continue
                cache[ck] = label
                out[i] = KillGroup(events=g.events, play_label=label)
                log.info("play_labels: %s -> %s", ck, label)
            except Exception as exc:
                log.warning("play_labels: Gemini failed for %s: %s", ck, exc)
                if "RESOURCE_EXHAUSTED" in str(exc) or "429" in str(exc):
                    log.warning("play_labels: quota hit; stopping further Gemini calls this run")
                    break

    _save_cache(cache_path, cache)
    return out



def label_multi_kills(
    *,
    enriched: list[EnrichedEvent],
    video_paths: list[Path],
    api_key: str,
    model: str = "gemini-2.5-flash",
    max_clips: int = 4,
) -> dict[int, str]:
    """Brief-compatible map ``{event_idx: label}`` for multi-kill finishers."""
    from src.ai.engine.kill_grouping import build_play_flows

    plays = [g for g in build_play_flows(enriched) if len(g.events) >= 2]
    labeled = label_play_groups(
        plays,
        video_paths=video_paths,
        api_key=api_key,
        model=model,
        max_clips=max_clips,
    )
    # Map finishing event identity via timestamp + video.
    by_fin = {
        (g.video_index, round(g.kill_secs[-1], 2)): g.play_label
        for g in labeled
        if g.play_label
    }
    out: dict[int, str] = {}
    for i, e in enumerate(enriched):
        key = (int(e.event.video_index), round(float(e.event.timestamp_sec), 2))
        if key in by_fin:
            out[i] = by_fin[key]
    return out
