"""Fast disk writes for multi-GB uploads (chunked, no full-file buffering)."""

from __future__ import annotations

import re
from pathlib import Path

import aiofiles
from fastapi import UploadFile
from starlette.requests import Request

_CHUNK = 8 * 1024 * 1024  # 8 MiB
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._()\[\] -]+")


def safe_filename(name: str, fallback: str = "file.bin") -> str:
    base = Path(name or fallback).name
    cleaned = _SAFE_NAME.sub("_", base).strip(" ._")
    return cleaned or fallback


async def stream_request_to_path(request: Request, dest: Path) -> int:
    """Write raw request body to dest; returns bytes written."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    async with aiofiles.open(dest, "wb") as out:
        async for chunk in request.stream():
            if not chunk:
                continue
            await out.write(chunk)
            written += len(chunk)
    return written


async def stream_upload_file_to_path(upload: UploadFile, dest: Path) -> int:
    """Write an UploadFile to dest in chunks (avoids await read() of entire file)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    async with aiofiles.open(dest, "wb") as out:
        while True:
            chunk = await upload.read(_CHUNK)
            if not chunk:
                break
            await out.write(chunk)
            written += len(chunk)
    return written
