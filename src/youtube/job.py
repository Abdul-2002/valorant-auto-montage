from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx

from src.library.db import connect, library_db_path
from src.youtube.errors import YouTubeAuthError, YouTubeConfigError, YouTubeUploadError
from src.youtube.oauth import list_my_channels, refresh_access_token
from src.youtube.settings import oauth_settings
from src.youtube.store import claim_upload, finish_upload, get_channel, get_upload, require_upload_scope
from src.youtube.upload import start_resumable, upload_file


def run_upload(
    upload_id: str,
    *,
    client: httpx.Client | None = None,
    db_path: Path | None = None,
) -> dict[str, str]:
    conn = connect(db_path or library_db_path())
    owns_client = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(30.0, read=600.0))
    claimed = False
    try:
        existing = _already_uploaded(conn, upload_id)
        if existing is not None:
            return existing
        if not claim_upload(conn, upload_id):
            raise YouTubeUploadError("upload is no longer queued")
        claimed = True
        return _send(conn, http, upload_id)
    except Exception as exc:
        if claimed:
            finish_upload(conn, upload_id, status="failed", youtube_video_id=None, error=_public_message(exc))
        if isinstance(exc, YouTubeUploadError):
            raise
        raise YouTubeUploadError(_public_message(exc)) from None
    finally:
        conn.close()
        if owns_client:
            http.close()


def resolve_montage_output(storage_dir: Path, task_id: str, layout: str) -> Path:
    if not task_id or any(part in task_id for part in ("/", "\\", "..")):
        raise YouTubeUploadError("invalid task id")
    name = "montage_9x16.mp4" if layout == "9:16" else "montage_16x9.mp4"
    root = storage_dir.resolve()
    path = (root / "tasks" / task_id / "outputs" / name).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise YouTubeUploadError("invalid task id") from None
    return path


def _already_uploaded(conn: sqlite3.Connection, upload_id: str) -> dict[str, str] | None:
    row = get_upload(conn, upload_id)
    if row is None:
        raise YouTubeUploadError("upload not found")
    if row["status"] != "uploaded":
        return None
    return {"status": "uploaded", "youtube_video_id": str(row["youtube_video_id"] or "")}


def _send(conn: sqlite3.Connection, http: httpx.Client, upload_id: str) -> dict[str, str]:
    row = get_upload(conn, upload_id)
    if row is None:
        raise YouTubeUploadError("upload not found")
    channel = get_channel(conn, str(row["channel_id"]))
    if channel is None:
        raise YouTubeUploadError("channel is not connected")
    require_upload_scope(str(channel["scopes"]))
    settings = oauth_settings()
    access = refresh_access_token(
        http,
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        refresh_token=str(channel["refresh_token"]),
    )
    _require_selected_channel(http, access, str(row["channel_id"]))
    path = Path(str(row["source_path"]))
    if not path.is_file():
        raise YouTubeUploadError("montage file is missing")
    session = start_resumable(http, access_token=access, meta=_meta(row), size_bytes=path.stat().st_size)
    accepted = upload_file(http, session_uri=session, path=path, access_token=access)
    return _record(conn, upload_id, str(row["channel_id"]), accepted)


def _require_selected_channel(http: httpx.Client, access: str, channel_id: str) -> None:
    ids = {item["channel_id"] for item in list_my_channels(http, access)}
    if channel_id not in ids:
        raise YouTubeAuthError(
            "this token cannot access that channel; reconnect and pick it in Google's account chooser"
        )


def _record(
    conn: sqlite3.Connection,
    upload_id: str,
    channel_id: str,
    accepted: dict[str, str],
) -> dict[str, str]:
    video_id = accepted["youtube_video_id"]
    remote = accepted["channel_id"]
    if remote and remote != channel_id:
        finish_upload(
            conn,
            upload_id,
            status="channel_mismatch",
            youtube_video_id=video_id,
            error="YouTube stored the video on a different channel. Reconnect while choosing that channel.",
        )
        return {"status": "channel_mismatch", "youtube_video_id": video_id}
    finish_upload(conn, upload_id, status="uploaded", youtube_video_id=video_id, error=None)
    return {"status": "uploaded", "youtube_video_id": video_id}


def _meta(row: dict[str, object]) -> dict[str, object]:
    return {
        "title": row["title"],
        "description": row["description"],
        "tags": row["tags"],
        "privacy_status": row["privacy_status"],
        "category_id": row["category_id"],
    }


def _public_message(exc: Exception) -> str:
    if isinstance(exc, (YouTubeUploadError, YouTubeAuthError, YouTubeConfigError)):
        return str(exc)[:500]
    return f"{type(exc).__name__}: YouTube upload failed"
