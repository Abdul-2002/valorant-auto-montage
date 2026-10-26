from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from src.app.dependencies import get_storage_dir
from src.app.schemas.library import MontageUse, VideoDetailResponse, VideoListItem, VideoListResponse
from src.library.db import connect, library_db_path
from src.library.videos import clamp_page, count_videos, get_video, list_videos, montages_using

router = APIRouter()


@router.get("/videos", response_model=VideoListResponse)
def list_library_videos(
    limit: int = 20,
    offset: int = 0,
    storage_dir: Path = Depends(get_storage_dir),
) -> VideoListResponse:
    size, start = clamp_page(limit, offset)
    conn = connect(library_db_path(storage_dir))
    try:
        rows = list_videos(conn, limit=size, offset=start)
        total = count_videos(conn)
    finally:
        conn.close()
    return VideoListResponse(
        videos=[_list_item(row) for row in rows],
        limit=size,
        offset=start,
        total=total,
    )


@router.get("/videos/{video_id}", response_model=VideoDetailResponse)
def get_library_video(video_id: str, storage_dir: Path = Depends(get_storage_dir)) -> VideoDetailResponse:
    conn = connect(library_db_path(storage_dir))
    try:
        row = get_video(conn, video_id)
        uses = montages_using(conn, video_id) if row is not None else []
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="video not found")
    return _detail(row, uses)


def _list_item(row: dict[str, object]) -> VideoListItem:
    return VideoListItem(
        id=str(row["id"]),
        sha256=str(row["sha256"]),
        original_filename=str(row["original_filename"]),
        duration_sec=float(row["duration_sec"]),
        created_at=str(row["created_at"]),
        summary=str(row["summary"]) if row.get("summary") else None,
        summary_model=str(row["summary_model"]) if row.get("summary_model") else None,
    )


def _detail(row: dict[str, object], uses: list[dict[str, object]]) -> VideoDetailResponse:
    item = _list_item(row)
    return VideoDetailResponse(
        **item.model_dump(),
        width=int(row["width"]),
        height=int(row["height"]),
        fps=float(row["fps"]),
        size_bytes=int(row["size_bytes"]),
        local_path=str(row["local_path"]),
        montages=[
            MontageUse(
                id=str(use["id"]),
                song_title=str(use["song_title"]),
                ordinal=int(use["ordinal"]),
                created_at=str(use["created_at"]),
            )
            for use in uses
        ],
    )
