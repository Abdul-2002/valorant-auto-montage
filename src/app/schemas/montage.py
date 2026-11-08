from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.ai.schema import MontageScript


class CreateMontageResponse(BaseModel):
    task_id: str


class CreateFromPathsRequest(BaseModel):
    """Container paths under /videos and /songs (already bind-mounted)."""

    videos: list[str] = Field(min_length=1)
    music: str


class MountedFile(BaseModel):
    name: str
    path: str
    size_bytes: int


class MountedMediaResponse(BaseModel):
    videos: list[MountedFile]
    songs: list[MountedFile]


class StageSessionResponse(BaseModel):
    session_id: str


class StageFileResponse(BaseModel):
    session_id: str
    slot: str
    bytes_written: int


class CreateFromStageRequest(BaseModel):
    session_id: str
    num_videos: int = Field(ge=1)


class TaskSummary(BaseModel):
    task_id: str
    song_name: str = ""
    num_videos: int = 0
    has_highlights: bool = False
    has_selection: bool = False
    has_script: bool = False
    has_outputs: bool = False
    num_highlights: int = 0
    resume_path: str = "detect"
    mtime: float = 0.0


class TaskListResponse(BaseModel):
    tasks: list[TaskSummary]


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
    render: bool = True


class ScriptSaveResponse(BaseModel):
    task_id: str
    saved: bool = True
    render_task_id: str | None = None


class PlayFlowScores(BaseModel):
    impact: float
    watchability: float
    combined: float


class RecommendedPlay(BaseModel):
    id: str
    video_index: int
    kill_timestamps_sec: list[float]
    kill_count: int
    play_label: str = ""
    detector_score: float
    flow: PlayFlowScores
    recommended: bool = False


class SequenceFlowScores(BaseModel):
    pacing: float
    arc: float
    variety: float
    combined: float


class RecommendationsResponse(BaseModel):
    task_id: str
    plays: list[RecommendedPlay]
    recommended_ids: list[str]
    sequence_flow: SequenceFlowScores
    density: str = "standard"
    recommend_max_plays: int | None = None
    recommend_min_plays: int | None = None


class SelectionConfirmRequest(BaseModel):
    play_ids: list[str]
    density: str | None = None


class SelectionConfirmResponse(BaseModel):
    task_id: str
    play_ids: list[str]


class ComposeResponse(BaseModel):
    task_id: str
    clip_count: int
    duration_sec: float

