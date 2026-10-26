from __future__ import annotations

import re
from pathlib import Path

import httpx

from src.youtube.errors import YouTubeUploadError
from src.youtube.metadata import video_body

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
_CHUNK = 8 * 1024 * 1024


def start_resumable(
    client: httpx.Client,
    *,
    access_token: str,
    meta: dict[str, object],
    size_bytes: int,
) -> str:
    if size_bytes <= 0:
        raise YouTubeUploadError("montage file is empty")
    try:
        response = client.post(
            UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(size_bytes),
                "X-Upload-Content-Type": "video/mp4",
            },
            json=video_body(meta),
        )
    except httpx.HTTPError as exc:
        raise YouTubeUploadError(f"could not start YouTube upload ({type(exc).__name__})") from None
    if response.status_code not in (200, 201):
        raise YouTubeUploadError(f"YouTube refused to start the upload ({response.status_code})")
    location = response.headers.get("Location", "").strip()
    if not location:
        raise YouTubeUploadError("YouTube did not return a resumable upload URL")
    return location


def upload_file(
    client: httpx.Client,
    *,
    session_uri: str,
    path: Path,
    access_token: str,
    chunk_size: int = _CHUNK,
) -> dict[str, str]:
    total = path.stat().st_size
    offset = 0
    server_errors = 0
    with path.open("rb") as handle:
        while offset < total:
            handle.seek(offset)
            blob = handle.read(chunk_size)
            response = _put_chunk(client, session_uri, blob, offset, total, access_token)
            if response.status_code in (200, 201):
                return _accepted(response)
            if response.status_code == 308:
                nxt = resume_offset(response, fallback=offset + len(blob))
                if nxt <= offset:
                    raise YouTubeUploadError("YouTube resume offset did not advance")
                offset = nxt
                server_errors = 0
                continue
            if response.status_code >= 500 and server_errors < 3:
                server_errors += 1
                continue
            raise YouTubeUploadError(f"YouTube upload failed ({response.status_code})")
    raise YouTubeUploadError("upload ended before YouTube accepted the file")


def resume_offset(response: httpx.Response, *, fallback: int) -> int:
    match = re.search(r"(\d+)\s*$", response.headers.get("Range", ""))
    if match is None:
        return fallback
    return int(match.group(1)) + 1


def _put_chunk(
    client: httpx.Client,
    session_uri: str,
    blob: bytes,
    start: int,
    total: int,
    access_token: str,
) -> httpx.Response:
    end = start + len(blob) - 1
    try:
        return client.put(
            session_uri,
            content=blob,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Length": str(len(blob)),
                "Content-Type": "video/mp4",
                "Content-Range": f"bytes {start}-{end}/{total}",
            },
        )
    except httpx.HTTPError as exc:
        raise YouTubeUploadError(f"upload connection failed ({type(exc).__name__})") from None


def _accepted(response: httpx.Response) -> dict[str, str]:
    try:
        body = response.json()
    except Exception as exc:
        raise YouTubeUploadError("YouTube accepted the upload but returned no video") from None
    if not isinstance(body, dict):
        raise YouTubeUploadError("YouTube accepted the upload but returned no video")
    video_id = str(body.get("id") or "")
    if not video_id:
        raise YouTubeUploadError("YouTube accepted the upload but returned no video id")
    snippet = body.get("snippet") if isinstance(body.get("snippet"), dict) else {}
    return {"youtube_video_id": video_id, "channel_id": str(snippet.get("channelId") or "")}
