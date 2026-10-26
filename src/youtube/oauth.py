from __future__ import annotations

from urllib.parse import urlencode

import httpx

from src.youtube.errors import YouTubeAuthError
from src.youtube.settings import SCOPES

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"


def authorization_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
    )
    return f"{AUTH_URL}?{query}"


def exchange_code(
    client: httpx.Client,
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict[str, str]:
    response = client.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    body = _json_or_empty(response)
    if response.status_code != 200:
        raise YouTubeAuthError(f"Google token exchange failed ({_error_code(body)})")
    refresh = str(body.get("refresh_token") or "")
    access = str(body.get("access_token") or "")
    if not refresh or not access:
        raise YouTubeAuthError("Google did not return a refresh token; reconnect and grant offline access")
    return {"refresh_token": refresh, "access_token": access, "scope": str(body.get("scope") or "")}


def refresh_access_token(
    client: httpx.Client,
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> str:
    response = client.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    body = _json_or_empty(response)
    if response.status_code != 200:
        raise YouTubeAuthError(f"Google refused to refresh the YouTube token ({_error_code(body)})")
    access = str(body.get("access_token") or "")
    if not access:
        raise YouTubeAuthError("Google refresh response had no access token")
    return access


def list_my_channels(client: httpx.Client, access_token: str) -> list[dict[str, str]]:
    """Channels this token can act as. videos.insert has no channel id parameter."""
    found: list[dict[str, str]] = []
    page: str | None = None
    for _ in range(5):
        params: dict[str, str] = {"part": "snippet", "mine": "true", "maxResults": "50"}
        if page:
            params["pageToken"] = page
        response = client.get(CHANNELS_URL, params=params, headers={"Authorization": f"Bearer {access_token}"})
        body = _json_or_empty(response)
        if response.status_code != 200:
            raise YouTubeAuthError(f"YouTube channel list failed ({_error_code(body)})")
        found.extend(_channel_rows(body))
        page = str(body.get("nextPageToken") or "") or None
        if page is None:
            break
    return found


def _channel_rows(body: dict[str, object]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    items = body.get("items")
    if not isinstance(items, list):
        return rows
    for item in items:
        if not isinstance(item, dict):
            continue
        channel_id = str(item.get("id") or "")
        snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
        title = str(snippet.get("title") or channel_id)
        if channel_id:
            rows.append({"channel_id": channel_id, "title": title})
    return rows


def _json_or_empty(response: httpx.Response) -> dict[str, object]:
    try:
        body = response.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _error_code(body: dict[str, object]) -> str:
    code = str(body.get("error") or "")
    if not code or len(code) > 80:
        return "http_error"
    return code
