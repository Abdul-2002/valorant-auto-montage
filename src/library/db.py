from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    original_filename TEXT NOT NULL,
    local_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    duration_sec REAL NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    fps REAL NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_summaries (
    video_id TEXT PRIMARY KEY REFERENCES videos(id),
    model TEXT NOT NULL,
    summary TEXT NOT NULL,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS montages (
    id TEXT PRIMARY KEY,
    song_title TEXT NOT NULL DEFAULT '',
    output_16x9 TEXT,
    output_9x16 TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS montage_sources (
    montage_id TEXT NOT NULL REFERENCES montages(id),
    video_id TEXT NOT NULL REFERENCES videos(id),
    ordinal INTEGER NOT NULL,
    PRIMARY KEY (montage_id, ordinal)
);

CREATE TABLE IF NOT EXISTS youtube_oauth_states (
    state TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS youtube_channels (
    channel_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    scopes TEXT NOT NULL,
    connected_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS youtube_uploads (
    id TEXT PRIMARY KEY,
    montage_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    privacy_status TEXT NOT NULL,
    category_id TEXT NOT NULL,
    source_path TEXT NOT NULL,
    youtube_video_id TEXT,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def library_db_path(storage_dir: Path | None = None) -> Path:
    if storage_dir is None:
        from src.app.dependencies import get_storage_dir

        root = get_storage_dir()
    else:
        root = storage_dir
    return root / "library.sqlite3"


def connect(path: Path) -> sqlite3.Connection:
    """Open the library database and create tables on first use."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn
