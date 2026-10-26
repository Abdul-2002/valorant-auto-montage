from __future__ import annotations

from pydantic import BaseModel, Field


class YouTubeChannelResponse(BaseModel):
    channel_id: str
    title: str
    connected_at: str | None = None


class YouTubeChannelsResponse(BaseModel):
    channels: list[YouTubeChannelResponse]


class YouTubeUploadRequest(BaseModel):
    task_id: str
    channel_id: str
    title: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    privacy_status: str = "private"
    format: str = "16:9"
    category_id: str = "20"


class YouTubeUploadQueued(BaseModel):
    upload_id: str
    status: str


class YouTubeUploadStatus(BaseModel):
    upload_id: str
    montage_id: str
    channel_id: str
    title: str
    description: str
    tags: list[str]
    privacy_status: str
    category_id: str
    youtube_video_id: str | None = None
    status: str
    error: str | None = None
    created_at: str
