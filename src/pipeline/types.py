from __future__ import annotations

from pydantic import BaseModel, Field


class DetectedEvent(BaseModel):
    video_index: int
    timestamp_sec: float
    score: float = Field(ge=0.0, le=1.0)
    event_type: str
