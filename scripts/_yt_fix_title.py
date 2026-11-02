"""Update YouTube video title/description for the Mood upload."""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from src.library.db import connect, library_db_path
from src.youtube.oauth import refresh_access_token
from src.youtube.settings import oauth_settings
from src.youtube.store import get_channel, get_upload

UPLOAD_ID = "b1d254fd24b94188b8c4decdeae60de9"
NEW_TITLE = "24kGoldn - Mood | Valorant Montage"


def main() -> int:
    conn = connect(library_db_path(Path("/data")))
    try:
        row = get_upload(conn, UPLOAD_ID)
        if row is None:
            raise SystemExit("upload not found")
        channel = get_channel(conn, str(row["channel_id"]))
        if channel is None:
            raise SystemExit("channel missing")
        video_id = str(row["youtube_video_id"] or "")
        if not video_id:
            raise SystemExit("no video id")
        settings = oauth_settings()
        with httpx.Client(timeout=60.0) as client:
            access = refresh_access_token(
                client,
                client_id=settings.client_id,
                client_secret=settings.client_secret,
                refresh_token=str(channel["refresh_token"]),
            )
            get = client.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "snippet", "id": video_id},
                headers={"Authorization": f"Bearer {access}"},
            )
            get.raise_for_status()
            items = get.json().get("items") or []
            if not items:
                raise SystemExit("video not found on YouTube")
            snippet = items[0]["snippet"]
            snippet["title"] = NEW_TITLE
            # Keep categoryId required by update
            body = {"id": video_id, "snippet": snippet}
            put = client.put(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "snippet"},
                headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
                json=body,
            )
            print("status", put.status_code, flush=True)
            print(put.text[:500], flush=True)
            put.raise_for_status()
        print(f"https://www.youtube.com/watch?v={video_id}", flush=True)
        print("title_updated", NEW_TITLE, flush=True)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
