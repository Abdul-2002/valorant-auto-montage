from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Annotated

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from src.app.dependencies import get_config, get_storage_dir
from src.app.schemas.montage import (
    ConfirmRequest,
    ConfirmResponse,
    CreateMontageResponse,
    HighlightsResponse,
    ScriptResponse,
    ScriptUpdateRequest,
    StatusResponse,
)
from src.config import AppConfig
from src.worker.celery_app import celery_app
from src.worker.tasks import detect_highlights_task, render_montage_task

router = APIRouter()


def _task_dir(storage_dir: Path, task_id: str) -> Path:
    return storage_dir / "tasks" / task_id


def _rewrite_paths(old_root: Path, new_root: Path, paths: list[str]) -> list[str]:
    out: list[str] = []
    for p in paths:
        try:
            pp = Path(p)
            out.append(str(new_root / pp.relative_to(old_root)))
        except Exception:
            out.append(p)
    return out


@router.post("/create", response_model=CreateMontageResponse)
async def create_montage(
    videos: Annotated[list[UploadFile], File(...)],
    music: Annotated[UploadFile | None, File()] = None,
    config: AppConfig = Depends(get_config),
    storage_dir: Path = Depends(get_storage_dir),
) -> CreateMontageResponse:
    storage_dir.mkdir(parents=True, exist_ok=True)
    # Create a task directory first to avoid worker race conditions where the task
    # starts before inputs/meta are written.
    tmp_id = uuid.uuid4().hex
    tdir = storage_dir / "tasks" / "pending" / tmp_id
    tdir.mkdir(parents=True, exist_ok=True)

    video_paths: list[str] = []
    for idx, vf in enumerate(videos):
        (tdir / "inputs").mkdir(parents=True, exist_ok=True)
        out_path = tdir / "inputs" / f"video_{idx}_{vf.filename or 'input.mp4'}"
        out_path.write_bytes(await vf.read())
        video_paths.append(str(out_path))

    music_path: str | None = None
    if music is not None:
        (tdir / "inputs").mkdir(parents=True, exist_ok=True)
        mp = tdir / "inputs" / f"music_{music.filename or 'music.mp3'}"
        mp.write_bytes(await music.read())
        music_path = str(mp)

    meta = {"videos": video_paths, "music": music_path}
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # Enqueue after inputs are fully written.
    task = detect_highlights_task.delay(
        {
            "num_videos": len(videos),
            "has_music": bool(music),
            "config": config.model_dump(mode="json"),
        }
    )

    # Move pending directory to task_id directory.
    final_tdir = _task_dir(storage_dir, task.id)
    if final_tdir.exists():
        raise HTTPException(status_code=409, detail="Task directory already exists")
    tdir.rename(final_tdir)

    # Rewrite meta.json paths after rename (they were written under pending/tmp_id).
    meta_path = final_tdir / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["videos"] = _rewrite_paths(tdir, final_tdir, meta.get("videos", []))
        if meta.get("music"):
            meta["music"] = _rewrite_paths(tdir, final_tdir, [meta["music"]])[0]
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # Persist the effective config used for detection for later rendering.
    (final_tdir / "detect_config.json").write_text(config.model_dump_json(indent=2), encoding="utf-8")

    return CreateMontageResponse(task_id=task.id)


@router.get("/{task_id}/status", response_model=StatusResponse)
def get_status(task_id: str) -> StatusResponse:
    ar = AsyncResult(task_id, app=celery_app)
    meta: dict[str, Any] = ar.info if isinstance(ar.info, dict) else {}

    progress = float(meta.get("progress", 0.0)) if meta else 0.0
    phase = meta.get("phase")

    return StatusResponse(task_id=task_id, state=ar.state, progress=progress, phase=phase, detail=meta or None)


@router.get("/{task_id}/highlights", response_model=HighlightsResponse)
def get_highlights(task_id: str, storage_dir: Path = Depends(get_storage_dir)) -> HighlightsResponse:
    tdir = _task_dir(storage_dir, task_id)
    hl_path = tdir / "highlights.json"
    if not hl_path.exists():
        raise HTTPException(status_code=404, detail="Highlights not ready")
    raw = json.loads(hl_path.read_text(encoding="utf-8"))
    return HighlightsResponse(task_id=task_id, highlights=raw["highlights"])


@router.post("/{task_id}/confirm", response_model=ConfirmResponse)
def confirm_highlights(
    task_id: str,
    body: ConfirmRequest,
    storage_dir: Path = Depends(get_storage_dir),
) -> ConfirmResponse:
    tdir = _task_dir(storage_dir, task_id)
    if not (tdir / "meta.json").exists():
        raise HTTPException(status_code=404, detail="Unknown task_id")

    (tdir / "confirmed.json").write_text(body.model_dump_json(indent=2), encoding="utf-8")

    render_task = render_montage_task.delay({"detect_task_id": task_id})
    return ConfirmResponse(task_id=task_id, render_task_id=render_task.id)


@router.get("/{task_id}/download")
def download(task_id: str, format: str = "16:9", storage_dir: Path = Depends(get_storage_dir)) -> dict[str, str]:
    tdir = _task_dir(storage_dir, task_id)
    out = tdir / "outputs" / ("montage_9x16.mp4" if format == "9:16" else "montage_16x9.mp4")
    if not out.exists():
        raise HTTPException(status_code=404, detail="Output not ready")
    return {"path": str(out)}


@router.get("/{task_id}/script", response_model=ScriptResponse)
def get_script(task_id: str, storage_dir: Path = Depends(get_storage_dir)) -> ScriptResponse:
    tdir = _task_dir(storage_dir, task_id)
    sp = tdir / "montage_script.json"
    if not sp.exists():
        raise HTTPException(status_code=404, detail="Script not ready")
    raw = json.loads(sp.read_text(encoding="utf-8"))
    from src.ai.schema import MontageScript

    script = MontageScript.model_validate(raw)
    return ScriptResponse(task_id=task_id, script=script)


@router.post("/{task_id}/script", response_model=ConfirmResponse)
def update_script_and_render(
    task_id: str,
    body: ScriptUpdateRequest,
    storage_dir: Path = Depends(get_storage_dir),
) -> ConfirmResponse:
    tdir = _task_dir(storage_dir, task_id)
    if not (tdir / "meta.json").exists():
        raise HTTPException(status_code=404, detail="Unknown task_id")

    (tdir / "montage_script.json").write_text(body.script.model_dump_json(indent=2), encoding="utf-8")

    render_task = render_montage_task.delay({"detect_task_id": task_id})
    return ConfirmResponse(task_id=task_id, render_task_id=render_task.id)
