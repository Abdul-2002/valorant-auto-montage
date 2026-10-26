"""Source-video library: one row per file hash, one Gemini summary."""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.library.catalog import index_task_videos
from src.library.db import connect
from src.library.videos import file_sha256, get_video, montages_using


class _Probe:
    width = 1920
    height = 1080
    fps = 60.0
    duration_sec = 1.0


def _probe(_path: Path) -> _Probe:
    return _Probe()


def test_should_reuse_a_summary_when_the_same_bytes_are_indexed_again() -> None:
    calls: list[Path] = []

    def _summarize(path: Path) -> str:
        calls.append(path)
        return '{"summary":"bind on Ascent","maps":["Ascent"],"agents":["Jett"],"notable_plays":[]}'

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        source = folder / "vod.mp4"
        source.write_bytes(b"same-vod-bytes")
        conn = connect(folder / "library.sqlite3")
        try:
            first = index_task_videos(
                conn,
                montage_id="montage-a",
                video_paths=[source],
                summarizer=_summarize,
                probe=_probe,
                model="gemini-2.5-flash-lite",
            )
            second = index_task_videos(
                conn,
                montage_id="montage-b",
                video_paths=[source],
                summarizer=_summarize,
                probe=_probe,
                model="gemini-2.5-flash-lite",
            )
            stored = get_video(conn, str(first[0]["video_id"]))
            uses = montages_using(conn, str(first[0]["video_id"]))
            digest = file_sha256(source)
        finally:
            conn.close()

    assert len(calls) == 1
    assert first[0]["reused"] is False
    assert second[0]["reused"] is True
    assert second[0]["video_id"] == first[0]["video_id"]
    assert second[0]["sha256"] == digest
    assert stored is not None
    assert stored["summary_model"] == "gemini-2.5-flash-lite"
    assert "Ascent" in str(stored["summary"])
    assert [row["id"] for row in uses] == ["montage-a", "montage-b"]


def test_should_keep_indexing_when_one_source_file_is_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        source = folder / "vod.mp4"
        source.write_bytes(b"present")
        conn = connect(folder / "library.sqlite3")
        try:
            rows = index_task_videos(
                conn,
                montage_id="montage-c",
                video_paths=[folder / "missing.mp4", source],
                summarizer=None,
                probe=_probe,
            )
        finally:
            conn.close()
    assert len(rows) == 1
    assert rows[0]["summary"] is None
