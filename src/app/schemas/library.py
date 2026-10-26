from __future__ import annotations

from pydantic import BaseModel


class MontageUse(BaseModel):
    id: str
    song_title: str
    ordinal: int
    created_at: str


class VideoListItem(BaseModel):
    id: str
    sha256: str
    original_filename: str
    duration_sec: float
    created_at: str
    summary: str | None = None
    summary_model: str | None = None


class VideoListResponse(BaseModel):
    videos: list[VideoListItem]
    limit: int
    offset: int
    total: int


class VideoDetailResponse(VideoListItem):
    width: int
    height: int
    fps: float
    size_bytes: int
    local_path: str
    montages: list[MontageUse]
