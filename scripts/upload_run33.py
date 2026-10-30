"""Upload artifacts/run33/outputs/montage_16x9.mp4 with public song-listing metadata."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.library.db import connect, library_db_path
from src.library.videos import ensure_montage, set_montage_outputs
from src.youtube.job import run_upload
from src.youtube.listing import build_upload_listing, load_script_duration, load_shot_times
from src.youtube.store import insert_upload, list_channels

SONG_TITLE = "HandClap"
SONG_CREDIT = "Song: HandClap - Fitz and the Tantrums."


def main() -> int:
    video = ROOT / "artifacts" / "run33" / "outputs" / "montage_16x9.mp4"
    if not video.is_file():
        print(f"MISSING {video}", flush=True)
        return 1

    script = ROOT / "artifacts" / "run33" / "montage_script.json"
    listing = build_upload_listing(
        song_title=SONG_TITLE,
        song_credit=SONG_CREDIT,
        shot_times_sec=load_shot_times(script),
        privacy_status="public",
        duration_sec=load_script_duration(script),
    )

    db = library_db_path(ROOT / "data")
    conn = connect(db)
    try:
        channels = list_channels(conn)
        if not channels:
            print("NO_CHANNEL", flush=True)
            return 1
        channel = channels[0]
        print(f"CHANNEL {channel['title']} {channel['channel_id']}", flush=True)
        set_montage_outputs(
            conn,
            "run33",
            output_16x9=str(video),
            output_9x16=str(ROOT / "artifacts" / "run33" / "outputs" / "montage_9x16.mp4"),
            song_title=SONG_TITLE,
        )
        ensure_montage(conn, "run33", song_title=SONG_TITLE)
        upload_id = insert_upload(
            conn,
            montage_id="run33",
            channel_id=str(channel["channel_id"]),
            title=str(listing["title"]),
            description=str(listing["description"]),
            tags=[str(tag) for tag in listing["tags"]],
            privacy_status=str(listing["privacy_status"]),
            category_id="20",
            source_path=str(video),
        )
    finally:
        conn.close()

    print(f"UPLOAD_STARTED {upload_id}", flush=True)
    print(f"TITLE {listing['title']}", flush=True)
    print(f"PRIVACY {listing['privacy_status']}", flush=True)
    result = run_upload(upload_id, db_path=db)
    print(f"UPLOAD_RESULT {result.get('status')} VIDEO_ID={result.get('youtube_video_id')}", flush=True)
    vid = result.get("youtube_video_id") or ""
    if vid:
        print(f"URL https://www.youtube.com/watch?v={vid}", flush=True)
    return 0 if result.get("status") == "uploaded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
