"""Optional multimodal play labels (ace / clutch / op) for top multi-kill moments.

Uses short Gemini video snippets around multi-kill bursts. Failures are non-fatal:
the montage still renders; only the director brief loses those labels.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from src.ai.enrichment import EnrichedEvent
from src.io.audio_loader import resolve_ffmpeg_exe

log = logging.getLogger(__name__)

_LABELS = frozenset({"ace", "clutch", "op", "multi", ""})


def _cut_clip(video: Path, center_sec: float, out: Path, *, pad: float = 2.5) -> bool:
    start = max(0.0, float(center_sec) - pad)
    ffmpeg = resolve_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(video),
        "-t",
        f"{pad * 2:.3f}",
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


def label_multi_kills(
    *,
    enriched: list[EnrichedEvent],
    video_paths: list[Path],
    api_key: str,
    model: str = "gemini-2.5-flash",
    max_clips: int = 4,
) -> dict[int, str]:
    """Return ``{event_idx: label}`` for the strongest multi-kill members."""
    if not api_key:
        return {}
    # Group by multi_kill_group_id; pick groups with size >= 3.
    groups: dict[str, list[int]] = {}
    for i, e in enumerate(enriched):
        gid = str(getattr(e, "multi_kill_group_id", "") or "")
        if not gid:
            continue
        groups.setdefault(gid, []).append(i)
    ranked = sorted(
        ((idxs, max(enriched[i].event.score for i in idxs)) for idxs in groups.values() if len(idxs) >= 3),
        key=lambda x: x[1],
        reverse=True,
    )[:max_clips]
    if not ranked:
        # Fall back: any event whose local gaps suggest a burst (handled by size-2 groups).
        ranked = sorted(
            ((idxs, max(enriched[i].event.score for i in idxs)) for idxs in groups.values() if len(idxs) >= 2),
            key=lambda x: x[1],
            reverse=True,
        )[:max_clips]
    if not ranked:
        return {}

    try:
        from google import genai
    except Exception:
        log.exception("play_labels: google-genai unavailable")
        return {}

    client = genai.Client(api_key=api_key)
    out: dict[int, str] = {}
    with tempfile.TemporaryDirectory(prefix="play_labels_") as tmp:
        tmp_path = Path(tmp)
        for idxs, _score in ranked:
            i = idxs[-1]  # label the finishing kill
            e = enriched[i]
            vpath = video_paths[int(e.event.video_index)]
            clip = tmp_path / f"kill_{i}.mp4"
            if not _cut_clip(vpath, float(e.event.timestamp_sec), clip):
                continue
            prompt = (
                "You are labeling a Valorant multi-kill clip for a montage director. "
                "Reply with ONE word only from: ace, clutch, op, multi. "
                "ace=5 kills in the round feel; clutch=low-hp / last-alive feel; "
                "op=Operator/sniper highlight; multi=other multi-kill."
            )
            try:
                uploaded = client.files.upload(file=str(clip))
                resp = client.models.generate_content(
                    model=model,
                    contents=[uploaded, prompt],
                )
                text = (getattr(resp, "text", None) or "").strip().lower().split()[0]
                text = "".join(ch for ch in text if ch.isalpha())
                if text in _LABELS and text:
                    out[i] = text
                    log.info("play_labels: event %d -> %s", i, text)
            except Exception as exc:
                log.warning("play_labels: Gemini failed for event %d: %s", i, exc)
    return out
