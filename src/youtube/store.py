from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from src.library.db import utc_now
from src.youtube.errors import YouTubeAuthError

_STATE_TTL_SEC = 600


def save_oauth_state(conn: sqlite3.Connection, state: str) -> None:
    conn.execute("DELETE FROM youtube_oauth_states WHERE created_at < ?", (_expired_before(),))
    conn.execute(
        "INSERT INTO youtube_oauth_states (state, created_at) VALUES (?, ?)",
        (state, utc_now()),
    )
    conn.commit()


def consume_oauth_state(conn: sqlite3.Connection, state: str) -> bool:
    """Delete the state even when it is expired so it cannot be replayed."""
    row = conn.execute(
        "SELECT created_at FROM youtube_oauth_states WHERE state = ?",
        (state,),
    ).fetchone()
    conn.execute("DELETE FROM youtube_oauth_states WHERE state = ?", (state,))
    conn.commit()
    if row is None:
        return False
    created = datetime.fromisoformat(str(row["created_at"]))
    age = (datetime.now(timezone.utc) - created).total_seconds()
    return age <= _STATE_TTL_SEC


def save_channel(
    conn: sqlite3.Connection,
    *,
    channel_id: str,
    title: str,
    refresh_token: str,
    scopes: str,
) -> None:
    conn.execute(
        """
        INSERT INTO youtube_channels (channel_id, title, refresh_token, scopes, connected_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET
            title = excluded.title,
            refresh_token = excluded.refresh_token,
            scopes = excluded.scopes,
            connected_at = excluded.connected_at
        """,
        (channel_id, title, refresh_token, scopes, utc_now()),
    )
    conn.commit()


def list_channels(conn: sqlite3.Connection) -> list[dict[str, str]]:
    rows = conn.execute(
        "SELECT channel_id, title, connected_at FROM youtube_channels ORDER BY title"
    ).fetchall()
    return [dict(row) for row in rows]


def get_channel(conn: sqlite3.Connection, channel_id: str) -> dict[str, str] | None:
    row = conn.execute(
        """
        SELECT channel_id, title, refresh_token, scopes, connected_at
          FROM youtube_channels WHERE channel_id = ?
        """,
        (channel_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def insert_upload(
    conn: sqlite3.Connection,
    *,
    montage_id: str,
    channel_id: str,
    title: str,
    description: str,
    tags: list[str],
    privacy_status: str,
    category_id: str,
    source_path: str,
) -> str:
    upload_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO youtube_uploads (
            id, montage_id, channel_id, title, description, tags_json,
            privacy_status, category_id, source_path, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)
        """,
        (
            upload_id,
            montage_id,
            channel_id,
            title,
            description,
            json.dumps(tags),
            privacy_status,
            category_id,
            source_path,
            utc_now(),
        ),
    )
    conn.commit()
    return upload_id


def get_upload(conn: sqlite3.Connection, upload_id: str) -> dict[str, object] | None:
    row = conn.execute("SELECT * FROM youtube_uploads WHERE id = ?", (upload_id,)).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["tags"] = json.loads(str(data.pop("tags_json") or "[]"))
    data.pop("refresh_token", None)
    return data


def claim_upload(conn: sqlite3.Connection, upload_id: str) -> bool:
    cursor = conn.execute(
        "UPDATE youtube_uploads SET status = 'uploading', error = NULL WHERE id = ? AND status = 'queued'",
        (upload_id,),
    )
    conn.commit()
    return cursor.rowcount == 1


def finish_upload(
    conn: sqlite3.Connection,
    upload_id: str,
    *,
    status: str,
    youtube_video_id: str | None,
    error: str | None,
) -> None:
    conn.execute(
        """
        UPDATE youtube_uploads
           SET status = ?, youtube_video_id = ?, error = ?
         WHERE id = ?
        """,
        (status, youtube_video_id, error, upload_id),
    )
    conn.commit()


def require_upload_scope(scopes: str) -> None:
    tokens = set(scopes.split())
    upload = "https://www.googleapis.com/auth/youtube.upload"
    broad = "https://www.googleapis.com/auth/youtube"
    if upload not in tokens and broad not in tokens:
        raise YouTubeAuthError("connected token is missing the youtube.upload scope; reconnect the channel")


def _expired_before() -> str:
    cutoff = datetime.now(timezone.utc).timestamp() - _STATE_TTL_SEC
    return datetime.fromtimestamp(cutoff, timezone.utc).replace(microsecond=0).isoformat()
