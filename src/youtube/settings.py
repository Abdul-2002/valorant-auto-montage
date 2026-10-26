from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from src.youtube.errors import YouTubeConfigError

_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
SCOPES = f"{_UPLOAD_SCOPE} {_READONLY_SCOPE}"


@dataclass(frozen=True)
class OAuthSettings:
    client_id: str
    client_secret: str
    redirect_uri: str


def oauth_settings(client_file: Path | None = None) -> OAuthSettings:
    """Env vars win when they are set. Otherwise use the Google client JSON."""
    configured = _from_env()
    if configured is not None:
        return configured
    path = client_file if client_file is not None else _find_client_file()
    if path is None or not path.is_file():
        raise YouTubeConfigError(
            "Set YOUTUBE_OAUTH_CLIENT_ID and YOUTUBE_OAUTH_CLIENT_SECRET, "
            "or download the Google client JSON into the project root"
        )
    return oauth_settings_from_file(path)


def oauth_settings_from_file(path: Path) -> OAuthSettings:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise YouTubeConfigError(f"Could not read the Google client file ({type(exc).__name__})") from None
    block = raw.get("installed") if isinstance(raw, dict) else None
    if not isinstance(block, dict):
        block = raw.get("web") if isinstance(raw, dict) else None
    if not isinstance(block, dict):
        raise YouTubeConfigError("Google client file has no installed or web client")
    client_id = str(block.get("client_id") or "").strip()
    client_secret = str(block.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        raise YouTubeConfigError("Google client file is missing the client id or secret")
    redirects = block.get("redirect_uris") if isinstance(block.get("redirect_uris"), list) else []
    redirect_uri = os.environ.get("YOUTUBE_OAUTH_REDIRECT_URI", "").strip()
    if not redirect_uri:
        redirect_uri = str(redirects[0]).strip() if redirects else "http://localhost"
    if not redirect_uri:
        raise YouTubeConfigError("Google client file has no redirect URI")
    return OAuthSettings(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)


def _from_env() -> OAuthSettings | None:
    client_id = os.environ.get("YOUTUBE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YOUTUBE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id and not client_secret:
        return None
    if not client_id or not client_secret:
        raise YouTubeConfigError("Set YOUTUBE_OAUTH_CLIENT_ID and YOUTUBE_OAUTH_CLIENT_SECRET")
    redirect_uri = os.environ.get(
        "YOUTUBE_OAUTH_REDIRECT_URI",
        "http://127.0.0.1:8000/youtube/callback",
    ).strip()
    if not redirect_uri:
        raise YouTubeConfigError("Set YOUTUBE_OAUTH_REDIRECT_URI")
    return OAuthSettings(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)


def _find_client_file() -> Path | None:
    explicit = os.environ.get("YOUTUBE_OAUTH_CLIENT_JSON", "").strip()
    if explicit:
        return Path(explicit)
    root = Path(__file__).resolve().parents[2]
    matches = sorted(root.glob("client_secret*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return matches[0] if matches else None
