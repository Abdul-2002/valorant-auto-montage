"""YouTube OAuth and resumable upload. No network calls."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from src.library.db import connect
from src.youtube.errors import YouTubeAuthError, YouTubeConfigError, YouTubeUploadError
from src.youtube.job import resolve_montage_output, run_upload
from src.youtube.metadata import clean_metadata
from src.youtube.oauth import authorization_url
from src.youtube.settings import SCOPES, oauth_settings
from src.youtube.store import (
    consume_oauth_state,
    get_upload,
    insert_upload,
    list_channels,
    require_upload_scope,
    save_channel,
    save_oauth_state,
)
from src.youtube.upload import start_resumable, upload_file

_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
_REFRESH = "refresh-secret-value"


def test_should_request_upload_and_readonly_scopes_with_offline_access() -> None:
    url = authorization_url(client_id="client", redirect_uri="http://127.0.0.1:8000/youtube/callback", state="abc")
    query = parse_qs(urlparse(url).query)
    assert query["scope"][0] == SCOPES
    assert "youtube.upload" in query["scope"][0]
    assert "youtube.readonly" in query["scope"][0]
    assert query["access_type"][0] == "offline"
    assert query["prompt"][0] == "consent"
    assert query["state"][0] == "abc"


def test_should_reject_a_token_that_cannot_upload() -> None:
    try:
        require_upload_scope("https://www.googleapis.com/auth/youtube.readonly")
    except YouTubeAuthError:
        return
    raise AssertionError("readonly scope was accepted")


def test_should_reject_youtube_metadata_that_the_api_will_not_accept() -> None:
    private = clean_metadata(
        title="  Ace   round  ",
        description="bind retake",
        tags=["Jett", "jett"],
        privacy_status="private",
        category_id="20",
    )
    assert private["title"] == "Ace round"
    assert private["tags"] == ["Jett"]
    for kwargs in (
        {"title": " ", "description": "", "tags": [], "privacy_status": "private", "category_id": "20"},
        {"title": "Ace", "description": "", "tags": [], "privacy_status": "secret", "category_id": "20"},
        {"title": "Ace", "description": "", "tags": ["x" * 31], "privacy_status": "private", "category_id": "20"},
        {"title": "Ace", "description": "", "tags": [], "privacy_status": "private", "category_id": "20;drop"},
    ):
        try:
            clean_metadata(**kwargs)
        except YouTubeUploadError:
            continue
        raise AssertionError(f"accepted invalid metadata: {kwargs}")


def test_should_drop_an_expired_oauth_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        conn = connect(Path(tmp) / "library.sqlite3")
        try:
            conn.execute(
                "INSERT INTO youtube_oauth_states (state, created_at) VALUES (?, ?)",
                ("old", "2020-01-01T00:00:00+00:00"),
            )
            conn.commit()
            expired = consume_oauth_state(conn, "old")
            save_oauth_state(conn, "fresh")
            fresh = consume_oauth_state(conn, "fresh")
            replay = consume_oauth_state(conn, "fresh")
        finally:
            conn.close()
    assert expired is False
    assert fresh is True
    assert replay is False


def test_should_resume_a_youtube_upload_after_308() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "montage_16x9.mp4"
        path.write_bytes(b"0123456789abcdef")
        calls = {"put": 0}

        def _handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(200, headers={"Location": "https://upload.example/session"})
            calls["put"] += 1
            if calls["put"] == 1:
                assert request.headers["Content-Range"] == "bytes 0-7/16"
                return httpx.Response(308, headers={"Range": "bytes=0-7"})
            assert request.headers["Content-Range"] == "bytes 8-15/16"
            return httpx.Response(201, json={"id": "vid123", "snippet": {"channelId": "chan"}})

        client = httpx.Client(transport=httpx.MockTransport(_handler))
        meta = clean_metadata(
            title="Ace",
            description="",
            tags=["valorant"],
            privacy_status="private",
            category_id="20",
        )
        session = start_resumable(client, access_token="access-token", meta=meta, size_bytes=path.stat().st_size)
        result = upload_file(client, session_uri=session, path=path, access_token="access-token", chunk_size=8)
        client.close()
    assert session == "https://upload.example/session"
    assert result == {"youtube_video_id": "vid123", "channel_id": "chan"}
    assert calls["put"] == 2


def test_should_upload_to_the_selected_channel_and_hide_the_refresh_token() -> None:
    _assert_upload(remote_channel="chan", expected_status="uploaded")


def test_should_record_a_channel_mismatch_without_deleting_the_private_video() -> None:
    _assert_upload(remote_channel="other", expected_status="channel_mismatch")


def test_should_mark_the_upload_failed_when_youtube_refuses_the_session() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        video = folder / "montage_16x9.mp4"
        video.write_bytes(b"mp4")
        conn = connect(folder / "library.sqlite3")
        try:
            save_channel(
                conn,
                channel_id="chan",
                title="Main",
                refresh_token=_REFRESH,
                scopes=_UPLOAD_SCOPE,
            )
            upload_id = insert_upload(
                conn,
                montage_id="task-1",
                channel_id="chan",
                title="Ace",
                description="",
                tags=[],
                privacy_status="private",
                category_id="20",
                source_path=str(video),
            )
        finally:
            conn.close()
        previous = _set_oauth_env()
        try:
            run_upload(
                upload_id,
                client=httpx.Client(transport=httpx.MockTransport(_refused)),
                db_path=folder / "library.sqlite3",
            )
        except YouTubeUploadError as exc:
            message = str(exc)
        else:
            _restore_env(previous)
            raise AssertionError("refused upload was treated as success")
        finally:
            _restore_env(previous)
        conn = connect(folder / "library.sqlite3")
        try:
            stored = get_upload(conn, upload_id)
        finally:
            conn.close()
    assert stored is not None
    assert stored["status"] == "failed"
    assert "403" in message
    assert _REFRESH not in message
    assert _REFRESH not in str(stored["error"])


def _refused(request: httpx.Request) -> httpx.Response:
    if request.url.host == "oauth2.googleapis.com":
        return httpx.Response(200, json={"access_token": "access-token"})
    if request.url.path.endswith("/channels"):
        return httpx.Response(200, json={"items": [{"id": "chan", "snippet": {"title": "Main"}}]})
    return httpx.Response(403)


def test_should_refuse_oauth_settings_when_the_client_is_unset() -> None:
    previous = _set_blank_oauth_env()
    try:
        oauth_settings(client_file=Path("missing-google-client.json"))
    except YouTubeConfigError:
        _restore_env(previous)
        return
    _restore_env(previous)
    raise AssertionError("missing OAuth client was accepted")


def test_should_read_the_google_client_json_when_env_is_blank() -> None:
    previous = _set_blank_oauth_env()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "client_secret_test.json"
            path.write_text(
                '{"installed":{"client_id":"id-from-file","client_secret":"secret-from-file","redirect_uris":["http://localhost"]}}',
                encoding="utf-8",
            )
            loaded = oauth_settings(client_file=path)
    finally:
        _restore_env(previous)
    assert loaded.client_id == "id-from-file"
    assert loaded.redirect_uri == "http://localhost"


def test_should_reject_a_task_id_that_escapes_storage() -> None:
    try:
        resolve_montage_output(Path("C:/storage"), "..\\..\\Windows", "16:9")
    except YouTubeUploadError:
        return
    raise AssertionError("path escape was accepted")


def _set_blank_oauth_env() -> dict[str, str | None]:
    keys = ("YOUTUBE_OAUTH_CLIENT_ID", "YOUTUBE_OAUTH_CLIENT_SECRET")
    previous = {key: os.environ.get(key) for key in keys}
    os.environ["YOUTUBE_OAUTH_CLIENT_ID"] = ""
    os.environ["YOUTUBE_OAUTH_CLIENT_SECRET"] = ""
    return previous


def _assert_upload(*, remote_channel: str, expected_status: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        video = folder / "montage_16x9.mp4"
        video.write_bytes(b"mp4")
        conn = connect(folder / "library.sqlite3")
        try:
            save_channel(
                conn,
                channel_id="chan",
                title="Main",
                refresh_token=_REFRESH,
                scopes=_UPLOAD_SCOPE,
            )
            upload_id = insert_upload(
                conn,
                montage_id="task-1",
                channel_id="chan",
                title="Ace",
                description="",
                tags=["valorant"],
                privacy_status="private",
                category_id="20",
                source_path=str(video),
            )
            public = list_channels(conn)
        finally:
            conn.close()
        previous = _set_oauth_env()
        try:
            result = run_upload(
                upload_id,
                client=httpx.Client(transport=httpx.MockTransport(_transport(remote_channel))),
                db_path=folder / "library.sqlite3",
            )
        finally:
            _restore_env(previous)
        conn = connect(folder / "library.sqlite3")
        try:
            stored = get_upload(conn, upload_id)
        finally:
            conn.close()
    assert public == [{"channel_id": "chan", "title": "Main", "connected_at": public[0]["connected_at"]}]
    assert "refresh_token" not in public[0]
    assert result["status"] == expected_status
    assert stored is not None
    assert stored["status"] == expected_status
    assert stored["youtube_video_id"] == "yt1"
    assert _REFRESH not in str(stored["error"])


def _transport(remote_channel: str):
    def _handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "access-token"})
        if request.url.path.endswith("/channels"):
            return httpx.Response(200, json={"items": [{"id": "chan", "snippet": {"title": "Main"}}]})
        if request.method == "POST":
            return httpx.Response(200, headers={"Location": "https://upload.example/session"})
        return httpx.Response(201, json={"id": "yt1", "snippet": {"channelId": remote_channel}})

    return _handler


def _set_oauth_env() -> dict[str, str | None]:
    keys = ("YOUTUBE_OAUTH_CLIENT_ID", "YOUTUBE_OAUTH_CLIENT_SECRET")
    previous = {key: os.environ.get(key) for key in keys}
    os.environ["YOUTUBE_OAUTH_CLIENT_ID"] = "test-client"
    os.environ["YOUTUBE_OAUTH_CLIENT_SECRET"] = "test-secret"
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
