from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.ai.schema import MontageScript


class CreateMontageResponse(BaseModel):
    task_id: str


class StatusResponse(BaseModel):
    task_id: str
    state: str
    progress: float = Field(ge=0.0, le=1.0, default=0.0)
    phase: str | None = None
    detail: dict[str, Any] | None = None


class HighlightItem(BaseModel):
    video_index: int
    timestamp_sec: float
    score: float = Field(ge=0.0, le=1.0)
    event_type: str


class HighlightsResponse(BaseModel):
    task_id: str
    highlights: list[HighlightItem]


class ConfirmRequest(BaseModel):
    highlights: list[HighlightItem]
    overrides: dict[str, Any] | None = None


class ConfirmResponse(BaseModel):
    task_id: str
    render_task_id: str


class ScriptResponse(BaseModel):
    task_id: str
    script: MontageScript


class ScriptUpdateRequest(BaseModel):
    script: MontageScript
