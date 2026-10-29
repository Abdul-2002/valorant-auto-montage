from __future__ import annotations

import hashlib
import sqlite3
import uuid
from pathlib import Path

from src.library.db import utc_now


def file_sha256(path: Path, chunk_bytes: int = 1024 * 1024) -> str:
    """Content hash so the same VOD reused in another montage is one row."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_bytes)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def upsert_video(
    conn: sqlite3.Connection,
    *,
    sha256: str,
    original_filename: str,
    local_path: str,
    size_bytes: int,
    duration_sec: float,
    width: int,
    height: int,
    fps: float,
) -> str:
    existing = conn.execute("SELECT id FROM videos WHERE sha256 = ?", (sha256,)).fetchone()
    if existing is not None:
        conn.execute(
            """
            UPDATE videos
               SET original_filename = ?, local_path = ?, size_bytes = ?,
                   duration_sec = ?, width = ?, height = ?, fps = ?
             WHERE id = ?
            """,
            (original_filename, local_path, size_bytes, duration_sec, width, height, fps, existing["id"]),
        )
        conn.commit()
        return str(existing["id"])

    video_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO videos (
            id, sha256, original_filename, local_path, size_bytes,
            duration_sec, width, height, fps, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            video_id,
            sha256,
            original_filename,
            local_path,
            size_bytes,
            duration_sec,
            width,
            height,
            fps,
            utc_now(),
        ),
    )
    conn.commit()
    return video_id


def get_summary(conn: sqlite3.Connection, video_id: str) -> str | None:
    row = conn.execute(
        "SELECT summary FROM video_summaries WHERE video_id = ?",
        (video_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row["summary"])


def save_summary(conn: sqlite3.Connection, video_id: str, *, model: str, summary: str) -> None:
    conn.execute(
        """
        INSERT INTO video_summaries (video_id, model, summary, generated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(video_id) DO UPDATE SET
            model = excluded.model,
            summary = excluded.summary,
            generated_at = excluded.generated_at
        """,
        (video_id, model, summary, utc_now()),
    )
    conn.commit()


def ensure_montage(conn: sqlite3.Connection, montage_id: str, song_title: str = "") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO montages (id, song_title, created_at) VALUES (?, ?, ?)",
        (montage_id, song_title, utc_now()),
    )
    if song_title:
        conn.execute(
            "UPDATE montages SET song_title = ? WHERE id = ? AND song_title = ''",
            (song_title, montage_id),
        )
    conn.commit()


def get_montage_song_title(conn: sqlite3.Connection, montage_id: str) -> str:
    row = conn.execute(
        "SELECT song_title FROM montages WHERE id = ?",
        (montage_id,),
    ).fetchone()
    if row is None:
        return ""
    return str(row["song_title"] or "")


def link_source(conn: sqlite3.Connection, montage_id: str, video_id: str, ordinal: int) -> None:
    conn.execute(
        """
        INSERT INTO montage_sources (montage_id, video_id, ordinal)
        VALUES (?, ?, ?)
        ON CONFLICT(montage_id, ordinal) DO UPDATE SET video_id = excluded.video_id
        """,
        (montage_id, video_id, ordinal),
    )
    conn.commit()


def set_montage_outputs(
    conn: sqlite3.Connection,
    montage_id: str,
    *,
    output_16x9: str | None,
    output_9x16: str | None,
    song_title: str,
) -> None:
    ensure_montage(conn, montage_id, song_title=song_title)
    conn.execute(
        "UPDATE montages SET output_16x9 = ?, output_9x16 = ? WHERE id = ?",
        (output_16x9, output_9x16, montage_id),
    )
    conn.commit()


def get_video(conn: sqlite3.Connection, video_id: str) -> dict[str, object] | None:
    row = conn.execute(
        """
        SELECT v.id, v.sha256, v.original_filename, v.local_path, v.size_bytes,
               v.duration_sec, v.width, v.height, v.fps, v.created_at,
               s.model AS summary_model, s.summary, s.generated_at AS summary_generated_at
          FROM videos v
          LEFT JOIN video_summaries s ON s.video_id = v.id
         WHERE v.id = ?
        """,
        (video_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def list_videos(conn: sqlite3.Connection, *, limit: int, offset: int) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT v.id, v.sha256, v.original_filename, v.duration_sec, v.created_at,
               s.summary, s.model AS summary_model
          FROM videos v
          LEFT JOIN video_summaries s ON s.video_id = v.id
         ORDER BY v.created_at DESC
         LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [dict(row) for row in rows]


def count_videos(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM videos").fetchone()
    return int(row["n"]) if row is not None else 0


def montages_using(conn: sqlite3.Connection, video_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT m.id, m.song_title, m.created_at, s.ordinal
          FROM montage_sources s
          JOIN montages m ON m.id = s.montage_id
         WHERE s.video_id = ?
         ORDER BY m.created_at, s.ordinal
        """,
        (video_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def clamp_page(limit: int, offset: int) -> tuple[int, int]:
    size = 20 if limit <= 0 else min(100, limit)
    return size, max(0, offset)
