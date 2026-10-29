"""Canonical YouTube title/description/tags for montage uploads."""
from __future__ import annotations

import json
import re
from pathlib import Path

_PLACEHOLDER_TITLE = re.compile(r"\b(montage|run\s*\d+)\b", re.IGNORECASE)
_PLACEHOLDER_DESC = re.compile(r"private\s+test\s+upload", re.IGNORECASE)


def song_hashtag_slug(song_title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", (song_title or "").lower())
    return slug or "valorant"


def format_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60}:{total % 60:02d}"


def shot_times_from_script(script: dict) -> list[float]:
    clips = script.get("clips") if isinstance(script, dict) else None
    if not isinstance(clips, list) or not clips:
        return []
    starts = [
        float(clip["output_start_sec"])
        for clip in clips
        if isinstance(clip, dict) and isinstance(clip.get("output_start_sec"), (int, float))
    ]
    if not starts:
        return []
    base = min(starts)
    times: list[float] = []
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        rel_start = float(clip.get("output_start_sec") or 0.0) - base
        kills = clip.get("kill_output_times_sec") or []
        if not isinstance(kills, list):
            continue
        for raw in kills:
            if isinstance(raw, (int, float)):
                times.append(rel_start + float(raw))
    times.sort()
    deduped: list[float] = []
    for t in times:
        if not deduped or abs(t - deduped[-1]) >= 0.45:
            deduped.append(t)
    return deduped


def _load_script(script_path: Path) -> dict | None:
    if not script_path.is_file():
        return None
    try:
        raw = json.loads(script_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def load_shot_times(script_path: Path) -> list[float]:
    raw = _load_script(script_path)
    return shot_times_from_script(raw) if raw is not None else []


def script_duration_sec(script: dict) -> float | None:
    clips = [c for c in script.get("clips") or [] if isinstance(c, dict)]
    starts = [float(c["output_start_sec"]) for c in clips if isinstance(c.get("output_start_sec"), (int, float))]
    ends = [float(c["output_end_sec"]) for c in clips if isinstance(c.get("output_end_sec"), (int, float))]
    return max(ends) - min(starts) if starts and ends else None


def load_script_duration(script_path: Path) -> float | None:
    raw = _load_script(script_path)
    return script_duration_sec(raw) if raw is not None else None


def chapter_times(
    shot_times_sec: list[float], *, duration_sec: float | None = None, min_gap_sec: float = 10.0
) -> list[float]:
    """YouTube chapters start at 0:00 and each must last >= 10s, including the last one."""
    marks = [0.0]
    for t in shot_times_sec:
        if t - marks[-1] >= min_gap_sec:
            marks.append(t)
    while duration_sec is not None and len(marks) > 1 and duration_sec - marks[-1] < min_gap_sec:
        marks.pop()
    return marks


def chapter_labels(count: int) -> list[str]:
    middle = ["Build", "Mid", "Climax", "Late"]
    inner = [middle[i] if i < len(middle) else f"Part {i + 2}" for i in range(max(0, count - 2))]
    return (["Intro"] + inner + ["Final"])[:count]


def build_upload_listing(
    *,
    song_title: str,
    song_credit: str | None = None,
    shot_times_sec: list[float] | None = None,
    privacy_status: str = "public",
    duration_sec: float | None = None,
) -> dict[str, object]:
    title = " ".join((song_title or "").split()) or "Valorant"
    credit = (song_credit or "").strip() or f"Song: {title}."
    shots = list(shot_times_sec or [])
    slug = song_hashtag_slug(title)
    hashtags = f"#valorantmontage #{slug} #valorant #montage #valorantclips"

    lines = [credit, ""]
    # Chapters go first: YouTube builds chapters from the first 0:00-led timestamp
    # list, and the dense shot list (2 s gaps) would not qualify.
    chapters = chapter_times(shots, duration_sec=duration_sec)
    if len(chapters) >= 3:
        lines.append("Chapters:")
        for t, label in zip(chapters, chapter_labels(len(chapters))):
            lines.append(f"{format_timestamp(t)} {label}")
        lines.append("")
    if shots:
        lines.append("Shots:")
        for index, t in enumerate(shots, 1):
            lines.append(f"{format_timestamp(t)} Shot {index}")
        lines.append("")
    lines.append(hashtags)
    description = "\n".join(lines).strip()

    tags = ["valorant", "montage", "valorantmontage", slug]
    if title.lower() not in {tag.lower() for tag in tags}:
        tags.insert(2, title[:30])

    return {
        "title": title[:100],
        "description": description[:5000],
        "tags": tags,
        "privacy_status": privacy_status if privacy_status in {"private", "unlisted", "public"} else "public",
    }


def is_placeholder_title(title: str) -> bool:
    return not title.strip() or bool(_PLACEHOLDER_TITLE.search(title))


def is_placeholder_description(description: str) -> bool:
    text = description.strip()
    return not text or bool(_PLACEHOLDER_DESC.search(text))


def merge_upload_listing(
    *,
    song_title: str,
    shot_times_sec: list[float] | None,
    title: str,
    description: str,
    tags: list[str],
    privacy_status: str,
    song_credit: str | None = None,
    duration_sec: float | None = None,
) -> dict[str, object]:
    """Prefer song-derived listing; keep explicit client values when they are intentional."""
    built = build_upload_listing(
        song_title=song_title or title,
        song_credit=song_credit,
        shot_times_sec=shot_times_sec,
        privacy_status=privacy_status or "public",
        duration_sec=duration_sec,
    )
    out_title = title.strip()
    if song_title.strip() and is_placeholder_title(out_title):
        out_title = str(built["title"])
    elif not out_title:
        out_title = str(built["title"])

    out_description = description.strip()
    if is_placeholder_description(out_description):
        out_description = str(built["description"])

    out_tags = [tag.strip() for tag in tags if tag.strip()] or list(built["tags"])
    privacy = privacy_status.strip().lower() if privacy_status else "public"
    if privacy not in {"private", "unlisted", "public"}:
        privacy = "public"

    return {
        "title": out_title[:100],
        "description": out_description[:5000],
        "tags": out_tags,
        "privacy_status": privacy,
    }


def script_path_for_task(storage_dir: Path, task_id: str) -> Path:
    primary = storage_dir / "tasks" / task_id / "montage_script.json"
    if primary.is_file():
        return primary
    # Local artifact runs (e.g. artifacts/run31) when STORAGE_DIR is ./data
    artifact = storage_dir.parent / "artifacts" / task_id / "montage_script.json"
    if artifact.is_file():
        return artifact
    return primary
