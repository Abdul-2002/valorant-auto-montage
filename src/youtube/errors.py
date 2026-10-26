from __future__ import annotations


class YouTubeConfigError(Exception):
    """OAuth client settings are missing. The message is safe to show."""


class YouTubeAuthError(Exception):
    """Google rejected the OAuth exchange or the channel list."""


class YouTubeUploadError(Exception):
    """The resumable upload did not finish. The message must not contain tokens."""
