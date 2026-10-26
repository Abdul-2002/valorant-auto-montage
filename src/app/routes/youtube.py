from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from src.app.dependencies import get_storage_dir
from src.app.schemas.youtube import (
    YouTubeChannelsResponse,
    YouTubeUploadQueued,
    YouTubeUploadRequest,
    YouTubeUploadStatus,
)
from src.library.db import connect, library_db_path
from src.library.videos import ensure_montage
from src.youtube.errors import YouTubeAuthError, YouTubeConfigError, YouTubeUploadError
from src.youtube.job import resolve_montage_output
from src.youtube.metadata import clean_metadata
from src.youtube.oauth import authorization_url, exchange_code, list_my_channels
from src.youtube.settings import OAuthSettings, oauth_settings
from src.youtube.store import (
    consume_oauth_state,
    finish_upload,
    get_channel,
    get_upload,
    insert_upload,
    list_channels,
    require_upload_scope,
    save_channel,
    save_oauth_state,
)
from src.worker.tasks import upload_youtube_task

router = APIRouter()


@router.get("/connect")
def connect_youtube(storage_dir: Path = Depends(get_storage_dir)) -> RedirectResponse:
    settings = _settings()
    state = secrets.token_urlsafe(32)
    conn = connect(library_db_path(storage_dir))
    try:
        save_oauth_state(conn, state)
    finally:
        conn.close()
    target = authorization_url(
        client_id=settings.client_id,
        redirect_uri=settings.redirect_uri,
        state=state,
    )
    return RedirectResponse(target)


@router.get("/callback", response_model=YouTubeChannelsResponse)
def youtube_callback(
    code: str = "",
    state: str = "",
    error: str = "",
    storage_dir: Path = Depends(get_storage_dir),
) -> YouTubeChannelsResponse:
    if error or not code or not state:
        raise HTTPException(status_code=400, detail="Google did not grant YouTube access")
    settings = _settings()
    conn = connect(library_db_path(storage_dir))
    try:
        return _finish_callback(conn, settings=settings, code=code, state=state)
    finally:
        conn.close()


@router.get("/channels", response_model=YouTubeChannelsResponse)
def youtube_channels(storage_dir: Path = Depends(get_storage_dir)) -> YouTubeChannelsResponse:
    conn = connect(library_db_path(storage_dir))
    try:
        return YouTubeChannelsResponse(channels=list_channels(conn))
    finally:
        conn.close()


@router.post("/uploads", response_model=YouTubeUploadQueued, status_code=202)
def queue_youtube_upload(
    body: YouTubeUploadRequest,
    storage_dir: Path = Depends(get_storage_dir),
) -> YouTubeUploadQueued:
    meta = _metadata(body)
    path = _output_path(storage_dir, body.task_id, str(meta["format"]))
    conn = connect(library_db_path(storage_dir))
    try:
        if get_channel(conn, body.channel_id) is None:
            raise HTTPException(status_code=404, detail="channel is not connected")
        ensure_montage(conn, body.task_id)
        upload_id = insert_upload(
            conn,
            montage_id=body.task_id,
            channel_id=body.channel_id,
            title=str(meta["title"]),
            description=str(meta["description"]),
            tags=_tags(meta),
            privacy_status=str(meta["privacy_status"]),
            category_id=str(meta["category_id"]),
            source_path=str(path),
        )
        _enqueue(conn, upload_id)
    finally:
        conn.close()
    return YouTubeUploadQueued(upload_id=upload_id, status="queued")


@router.get("/uploads/{upload_id}", response_model=YouTubeUploadStatus)
def youtube_upload_status(upload_id: str, storage_dir: Path = Depends(get_storage_dir)) -> YouTubeUploadStatus:
    conn = connect(library_db_path(storage_dir))
    try:
        row = get_upload(conn, upload_id)
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="upload not found")
    return _status(row)


def _finish_callback(
    conn: sqlite3.Connection,
    *,
    settings: OAuthSettings,
    code: str,
    state: str,
) -> YouTubeChannelsResponse:
    if not consume_oauth_state(conn, state):
        raise HTTPException(status_code=400, detail="OAuth state expired; start the connection again")
    try:
        channels = _exchange(settings, code)
    except YouTubeAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    for channel in channels:
        save_channel(
            conn,
            channel_id=channel["channel_id"],
            title=channel["title"],
            refresh_token=channel["refresh_token"],
            scopes=channel["scopes"],
        )
    public = [{"channel_id": item["channel_id"], "title": item["title"]} for item in channels]
    return YouTubeChannelsResponse(channels=public)


def _exchange(settings: OAuthSettings, code: str) -> list[dict[str, str]]:
    with httpx.Client(timeout=30.0) as client:
        tokens = exchange_code(
            client,
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            code=code,
            redirect_uri=settings.redirect_uri,
        )
        require_upload_scope(tokens["scope"])
        listed = list_my_channels(client, tokens["access_token"])
    if not listed:
        raise YouTubeAuthError("Google returned no YouTube channel for this account")
    return [
        {
            "channel_id": item["channel_id"],
            "title": item["title"],
            "refresh_token": tokens["refresh_token"],
            "scopes": tokens["scope"],
        }
        for item in listed
    ]


def _metadata(body: YouTubeUploadRequest) -> dict[str, object]:
    if body.format not in {"16:9", "9:16"}:
        raise HTTPException(status_code=400, detail="format must be 16:9 or 9:16")
    try:
        meta = clean_metadata(
            title=body.title,
            description=body.description,
            tags=body.tags,
            privacy_status=body.privacy_status,
            category_id=body.category_id,
        )
    except YouTubeUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    meta["format"] = body.format
    return meta


def _output_path(storage_dir: Path, task_id: str, layout: str) -> Path:
    try:
        path = resolve_montage_output(storage_dir, task_id, layout)
    except YouTubeUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="montage output is not ready")
    return path


def _settings() -> OAuthSettings:
    try:
        return oauth_settings()
    except YouTubeConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


def _tags(meta: dict[str, object]) -> list[str]:
    raw = meta["tags"]
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="tags are invalid")
    return [str(tag) for tag in raw]


def _enqueue(conn: sqlite3.Connection, upload_id: str) -> None:
    try:
        upload_youtube_task.delay({"upload_id": upload_id})
    except Exception:
        finish_upload(
            conn,
            upload_id,
            status="failed",
            youtube_video_id=None,
            error="could not queue the upload",
        )
        raise HTTPException(status_code=503, detail="could not queue the YouTube upload") from None


def _status(row: dict[str, object]) -> YouTubeUploadStatus:
    return YouTubeUploadStatus(
        upload_id=str(row["id"]),
        montage_id=str(row["montage_id"]),
        channel_id=str(row["channel_id"]),
        title=str(row["title"]),
        description=str(row["description"]),
        tags=[str(tag) for tag in row["tags"]] if isinstance(row["tags"], list) else [],
        privacy_status=str(row["privacy_status"]),
        category_id=str(row["category_id"]),
        youtube_video_id=str(row["youtube_video_id"]) if row["youtube_video_id"] else None,
        status=str(row["status"]),
        error=str(row["error"]) if row["error"] else None,
        created_at=str(row["created_at"]),
    )
