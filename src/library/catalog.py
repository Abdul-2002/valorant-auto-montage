from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path

from src.library.db import connect, library_db_path
from src.library.errors import LibraryError
from src.library.summaries import generate_video_summary
from src.library.videos import (
    ensure_montage,
    file_sha256,
    get_summary,
    link_source,
    save_summary,
    set_montage_outputs,
    upsert_video,
)

log = logging.getLogger(__name__)

Probe = Callable[[Path], object]
Summarizer = Callable[[Path], str]


def index_task_videos(
    conn: sqlite3.Connection,
    *,
    montage_id: str,
    video_paths: list[Path],
    song_title: str = "",
    summarizer: Summarizer | None = None,
    probe: Probe | None = None,
    model: str = "",
) -> list[dict[str, object]]:
    """Index source VODs. An existing summary for the same bytes is kept."""
    ensure_montage(conn, montage_id, song_title=song_title)
    rows: list[dict[str, object]] = []
    reader = probe or _default_probe
    for ordinal, raw in enumerate(video_paths):
        try:
            rows.append(
                _index_one(
                    conn,
                    montage_id=montage_id,
                    ordinal=ordinal,
                    path=Path(raw),
                    summarizer=summarizer,
                    probe=reader,
                    model=model,
                )
            )
        except LibraryError as exc:
            log.warning("skipped source %s of montage %s: %s", ordinal, montage_id, exc)
        except OSError:
            log.exception("failed to index source %s of montage %s", ordinal, montage_id)
    return rows


def index_detect_task(task_id: str, video_paths: list[str], *, api_key: str, model: str) -> None:
    conn = connect(library_db_path())
    try:
        summarizer = _summarizer(api_key, model) if api_key.strip() else None
        index_task_videos(
            conn,
            montage_id=task_id,
            video_paths=[Path(p) for p in video_paths],
            summarizer=summarizer,
            model=model,
        )
    finally:
        conn.close()


def record_rendered_outputs(task_id: str, out_dir: Path, song_title: str) -> None:
    wide = out_dir / "montage_16x9.mp4"
    tall = out_dir / "montage_9x16.mp4"
    conn = connect(library_db_path())
    try:
        set_montage_outputs(
            conn,
            task_id,
            output_16x9=str(wide) if wide.is_file() else None,
            output_9x16=str(tall) if tall.is_file() else None,
            song_title=song_title,
        )
    finally:
        conn.close()


def _default_probe(path: Path) -> object:
    from src.io.video_reader import get_video_info

    return get_video_info(path)


def _summarizer(api_key: str, model: str) -> Summarizer:
    def _run(path: Path) -> str:
        return generate_video_summary(path, api_key=api_key, model=model)

    return _run


def _index_one(
    conn: sqlite3.Connection,
    *,
    montage_id: str,
    ordinal: int,
    path: Path,
    summarizer: Summarizer | None,
    probe: Probe,
    model: str,
) -> dict[str, object]:
    if not path.is_file():
        raise LibraryError(f"source video missing: {path.name}")
    digest = file_sha256(path)
    info = _safe_probe(path, probe)
    video_id = upsert_video(
        conn,
        sha256=digest,
        original_filename=path.name,
        local_path=str(path),
        size_bytes=path.stat().st_size,
        duration_sec=float(info.duration_sec),
        width=int(info.width),
        height=int(info.height),
        fps=float(info.fps),
    )
    link_source(conn, montage_id, video_id, ordinal)
    existing = get_summary(conn, video_id)
    summary = existing if existing is not None else _try_summary(conn, video_id, path, summarizer, model)
    return {"video_id": video_id, "sha256": digest, "summary": summary, "reused": existing is not None}


def _safe_probe(path: Path, probe: Probe) -> object:
    try:
        return probe(path)
    except Exception as exc:
        log.warning("video probe failed for %s: %s", path.name, type(exc).__name__)
        return _EmptyProbe()


class _EmptyProbe:
    width = 0
    height = 0
    fps = 0.0
    duration_sec = 0.0


def _try_summary(
    conn: sqlite3.Connection,
    video_id: str,
    path: Path,
    summarizer: Summarizer | None,
    model: str,
) -> str | None:
    if summarizer is None:
        return None
    try:
        text = summarizer(path).strip()
    except Exception as exc:
        # The SDK exception can echo request data. Keep the log to the type.
        log.warning("video summary failed for %s: %s", path.name, type(exc).__name__)
        return None
    if not text:
        return None
    save_summary(conn, video_id, model=model or "gemini", summary=text)
    return text
