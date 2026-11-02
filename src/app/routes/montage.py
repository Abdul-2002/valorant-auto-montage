from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Annotated

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from src.app.dependencies import get_config, get_storage_dir
from src.app.media_paths import (
    link_or_copy,
    list_media_files,
    resolve_under_roots,
    song_roots,
    video_roots,
)
from src.app.schemas.montage import (
    ComposeResponse,
    ConfirmRequest,
    ConfirmResponse,
    CreateFromPathsRequest,
    CreateFromStageRequest,
    CreateMontageResponse,
    HighlightsResponse,
    MountedFile,
    MountedMediaResponse,
    RecommendationsResponse,
    ScriptResponse,
    ScriptUpdateRequest,
    SelectionConfirmRequest,
    SelectionConfirmResponse,
    StageFileResponse,
    StageSessionResponse,
    StatusResponse,
)
from src.app.upload_io import safe_filename, stream_request_to_path, stream_upload_file_to_path
from src.config import AppConfig
from src.worker.celery_app import celery_app
from src.worker.tasks import detect_highlights_task, render_montage_task

router = APIRouter()

_VIDEO_SUFFIXES = (".mp4", ".mkv", ".mov", ".webm", ".avi")
_SONG_SUFFIXES = (".mp3", ".wav", ".flac", ".m4a", ".ogg")


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


def _enqueue_detect_from_pending(
    *,
    tdir: Path,
    storage_dir: Path,
    config: AppConfig,
    num_videos: int,
    has_music: bool,
) -> str:
    """Finalize task dir (rewrite paths) BEFORE enqueue — avoids worker reading pending paths."""
    task_id = str(uuid.uuid4())
    final_tdir = _task_dir(storage_dir, task_id)
    if final_tdir.exists():
        raise HTTPException(status_code=409, detail="Task directory already exists")

    meta_path = tdir / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["videos"] = _rewrite_paths(tdir, final_tdir, meta.get("videos", []))
        if meta.get("music"):
            meta["music"] = _rewrite_paths(tdir, final_tdir, [meta["music"]])[0]
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    (tdir / "detect_config.json").write_text(config.model_dump_json(indent=2), encoding="utf-8")
    tdir.rename(final_tdir)

    detect_highlights_task.apply_async(
        args=[
            {
                "num_videos": num_videos,
                "has_music": has_music,
                "config": config.model_dump(mode="json"),
            }
        ],
        task_id=task_id,
    )
    return task_id


@router.get("/media/mounted", response_model=MountedMediaResponse)
def list_mounted_media() -> MountedMediaResponse:
    videos = [
        MountedFile(name=name, path=str(path), size_bytes=size)
        for name, path, size in list_media_files(video_roots(), _VIDEO_SUFFIXES)
    ]
    songs = [
        MountedFile(name=name, path=str(path), size_bytes=size)
        for name, path, size in list_media_files(song_roots(), _SONG_SUFFIXES)
    ]
    return MountedMediaResponse(videos=videos, songs=songs)


def _stage_root(storage_dir: Path, session_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id")
    return storage_dir / "tasks" / "staging" / session_id


@router.post("/stage/session", response_model=StageSessionResponse)
def create_stage_session(storage_dir: Path = Depends(get_storage_dir)) -> StageSessionResponse:
    session_id = str(uuid.uuid4())
    root = _stage_root(storage_dir, session_id)
    root.mkdir(parents=True, exist_ok=True)
    return StageSessionResponse(session_id=session_id)


@router.put("/stage/{session_id}/{slot}", response_model=StageFileResponse)
async def stage_raw_file(
    session_id: str,
    slot: str,
    request: Request,
    filename: str = Query(..., min_length=1),
    storage_dir: Path = Depends(get_storage_dir),
) -> StageFileResponse:
    """Raw-body upload (no multipart). Slot: video_0..N or music."""
    if not re.fullmatch(r"(video_\d+|music)", slot):
        raise HTTPException(status_code=400, detail="slot must be video_N or music")
    root = _stage_root(storage_dir, session_id)
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Unknown staging session")
    dest = root / f"{slot}_{safe_filename(filename)}"
    written = await stream_request_to_path(request, dest)
    if written <= 0:
        raise HTTPException(status_code=400, detail="Empty upload body")
    return StageFileResponse(session_id=session_id, slot=slot, bytes_written=written)


@router.post("/create-from-stage", response_model=CreateMontageResponse)
def create_montage_from_stage(
    body: CreateFromStageRequest,
    config: AppConfig = Depends(get_config),
    storage_dir: Path = Depends(get_storage_dir),
) -> CreateMontageResponse:
    """Assemble a detect task from a completed parallel staging session."""
    stage = _stage_root(storage_dir, body.session_id)
    if not stage.is_dir():
        raise HTTPException(status_code=404, detail="Unknown staging session")

    tmp_id = uuid.uuid4().hex
    tdir = storage_dir / "tasks" / "pending" / tmp_id
    inputs = tdir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)

    video_paths: list[str] = []
    for idx in range(body.num_videos):
        matches = sorted(stage.glob(f"video_{idx}_*"))
        if not matches:
            raise HTTPException(status_code=400, detail=f"Missing staged video_{idx}")
        dest = inputs / matches[0].name
        matches[0].replace(dest)
        video_paths.append(str(dest))

    music_matches = sorted(stage.glob("music_*"))
    if not music_matches:
        raise HTTPException(status_code=400, detail="Missing staged music")
    music_dest = inputs / music_matches[0].name
    music_matches[0].replace(music_dest)

    meta = {"videos": video_paths, "music": str(music_dest)}
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # Drop empty staging dir when possible.
    try:
        stage.rmdir()
    except OSError:
        pass

    task_id = _enqueue_detect_from_pending(
        tdir=tdir,
        storage_dir=storage_dir,
        config=config,
        num_videos=len(video_paths),
        has_music=True,
    )
    return CreateMontageResponse(task_id=task_id)


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
        out_path = tdir / "inputs" / f"video_{idx}_{safe_filename(vf.filename or 'input.mp4')}"
        await stream_upload_file_to_path(vf, out_path)
        video_paths.append(str(out_path))

    music_path: str | None = None
    if music is not None:
        (tdir / "inputs").mkdir(parents=True, exist_ok=True)
        mp = tdir / "inputs" / f"music_{safe_filename(music.filename or 'music.mp3')}"
        await stream_upload_file_to_path(music, mp)
        music_path = str(mp)

    meta = {"videos": video_paths, "music": music_path}
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    task_id = _enqueue_detect_from_pending(
        tdir=tdir,
        storage_dir=storage_dir,
        config=config,
        num_videos=len(videos),
        has_music=bool(music),
    )
    return CreateMontageResponse(task_id=task_id)


@router.post("/create-from-paths", response_model=CreateMontageResponse)
def create_montage_from_paths(
    body: CreateFromPathsRequest,
    config: AppConfig = Depends(get_config),
    storage_dir: Path = Depends(get_storage_dir),
) -> CreateMontageResponse:
    """Zero-copy create: symlink files already mounted at /videos and /songs."""
    storage_dir.mkdir(parents=True, exist_ok=True)
    tmp_id = uuid.uuid4().hex
    tdir = storage_dir / "tasks" / "pending" / tmp_id
    inputs = tdir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)

    video_paths: list[str] = []
    try:
        for idx, raw in enumerate(body.videos):
            src = resolve_under_roots(raw, video_roots())
            dst = inputs / f"video_{idx}_{src.name}"
            link_or_copy(src, dst)
            video_paths.append(str(dst))
        music_src = resolve_under_roots(body.music, song_roots())
        music_dst = inputs / f"music_{music_src.name}"
        link_or_copy(music_src, music_dst)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    meta = {"videos": video_paths, "music": str(music_dst)}
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    task_id = _enqueue_detect_from_pending(
        tdir=tdir,
        storage_dir=storage_dir,
        config=config,
        num_videos=len(video_paths),
        has_music=True,
    )
    return CreateMontageResponse(task_id=task_id)


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


@router.get("/{task_id}/media/video/{video_index}")
def media_video(task_id: str, video_index: int, storage_dir: Path = Depends(get_storage_dir)) -> FileResponse:
    """Stream a source VOD for studio preview."""
    tdir = _task_dir(storage_dir, task_id)
    meta_path = tdir / "meta.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Unknown task_id")
    videos = json.loads(meta_path.read_text(encoding="utf-8")).get("videos") or []
    if video_index < 0 or video_index >= len(videos):
        raise HTTPException(status_code=404, detail="video_index out of range")
    path = Path(videos[video_index])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Video file missing")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.get("/{task_id}/media/music")
def media_music(task_id: str, storage_dir: Path = Depends(get_storage_dir)) -> FileResponse:
    tdir = _task_dir(storage_dir, task_id)
    meta_path = tdir / "meta.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Unknown task_id")
    music = json.loads(meta_path.read_text(encoding="utf-8")).get("music")
    if not music:
        raise HTTPException(status_code=404, detail="No music on task")
    path = Path(music)
    if not path.is_file():
        # Prefer contiguous bed if already composed.
        bed = tdir / "song" / "music_contiguous.wav"
        if bed.is_file():
            return FileResponse(bed, media_type="audio/wav", filename=bed.name)
        raise HTTPException(status_code=404, detail="Music file missing")
    return FileResponse(path, media_type="audio/mpeg", filename=path.name)


def _plays_for_task(tdir: Path, config: AppConfig) -> list:
    from src.ai.enrichment import enrich_events
    from src.ai.engine.kill_grouping import build_play_flows
    from src.ai.play_labels import label_play_groups
    from src.pipeline.types import DetectedEvent

    hl_path = tdir / "highlights.json"
    if not hl_path.exists():
        raise HTTPException(status_code=404, detail="Highlights not ready")
    raw = json.loads(hl_path.read_text(encoding="utf-8"))
    events = [DetectedEvent.model_validate(x) for x in raw.get("highlights", raw)]
    meta = json.loads((tdir / "meta.json").read_text(encoding="utf-8"))
    video_paths = [Path(p) for p in meta.get("videos", [])]
    # Skip OpenCV probe + scoped CV — both hang on large OneDrive bind mounts
    # and made /recommendations exceed client timeouts.
    enriched, _ = enrich_events(
        highlights=events,
        video_paths=video_paths,
        detect_scope=False,
        probe_videos=False,
    )
    plays = build_play_flows(enriched)
    # Gemini play-labeling cuts each VOD via ffmpeg + uploads clips; on OneDrive
    # that blocks /recommendations for minutes. Prefer cache-only / unlabeled.
    cache = tdir / "play_labels.json"
    if cache.is_file():
        try:
            return label_play_groups(
                plays,
                video_paths=video_paths,
                api_key="",
                model="gemini-2.5-flash",
                cache_path=cache,
            )
        except Exception:
            return plays
    return plays


@router.get("/{task_id}/recommendations", response_model=RecommendationsResponse)
def get_recommendations(
    task_id: str,
    density: str | None = None,
    storage_dir: Path = Depends(get_storage_dir),
    config: AppConfig = Depends(get_config),
) -> RecommendationsResponse:
    from src.ai.engine.recommend import recommendations_payload

    tdir = _task_dir(storage_dir, task_id)
    if not (tdir / "meta.json").exists():
        raise HTTPException(status_code=404, detail="Unknown task_id")
    use_density = density or str(getattr(config.ai_director, "curation_density", "standard") or "standard")
    plays = _plays_for_task(tdir, config)
    payload = recommendations_payload(plays, density=use_density)
    (tdir / "recommendations.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return RecommendationsResponse(task_id=task_id, **payload)


@router.post("/{task_id}/recommendations/confirm", response_model=SelectionConfirmResponse)
def confirm_recommendations(
    task_id: str,
    body: SelectionConfirmRequest,
    storage_dir: Path = Depends(get_storage_dir),
) -> SelectionConfirmResponse:
    tdir = _task_dir(storage_dir, task_id)
    if not (tdir / "meta.json").exists():
        raise HTTPException(status_code=404, detail="Unknown task_id")
    if not body.play_ids:
        raise HTTPException(status_code=400, detail="play_ids required")
    selection = {"play_ids": list(body.play_ids), "density": body.density}
    (tdir / "selection.json").write_text(json.dumps(selection, indent=2), encoding="utf-8")
    return SelectionConfirmResponse(task_id=task_id, play_ids=list(body.play_ids))


@router.post("/{task_id}/compose", response_model=ComposeResponse)
def compose_preview(
    task_id: str,
    storage_dir: Path = Depends(get_storage_dir),
    config: AppConfig = Depends(get_config),
) -> ComposeResponse:
    """Build montage_script.json for editor preview without final encode."""
    from src.ai.director import generate_montage_script
    from src.pipeline.music_edit import prepare_edited_track

    tdir = _task_dir(storage_dir, task_id)
    meta_path = tdir / "meta.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Unknown task_id")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    videos = [Path(p) for p in meta.get("videos", [])]
    music = Path(meta["music"]) if meta.get("music") else None
    hl_path = tdir / "highlights.json"
    if not hl_path.exists():
        raise HTTPException(status_code=404, detail="Highlights not ready")
    highlights = json.loads(hl_path.read_text(encoding="utf-8")).get("highlights", [])

    beat_map = None
    if music is not None and music.is_file():
        _, beat_map = prepare_edited_track(
            music,
            cache_dir=tdir / "song",
            needed_sec=float(config.output.target_duration_sec),
            splice=False,
        )

    selected_ids: list[str] | None = None
    sel_path = tdir / "selection.json"
    if sel_path.exists():
        try:
            selected_ids = list(json.loads(sel_path.read_text(encoding="utf-8")).get("play_ids") or [])
        except Exception:
            selected_ids = None

    script, _ = generate_montage_script(
        highlights=highlights,
        video_paths=videos,
        config=config,
        beat_map=beat_map,
        brief=None,
        persist_path=tdir / "montage_script.json",
        selected_play_ids=selected_ids,
    )
    duration = 0.0
    if script.clips:
        duration = sum(
            max(0.0, float(c.output_end_sec or 0.0) - float(c.output_start_sec or 0.0)) for c in script.clips
        )
    return ComposeResponse(task_id=task_id, clip_count=len(script.clips), duration_sec=float(duration))


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
