"""Resolve and link bind-mounted media under /videos and /songs."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

DEFAULT_VIDEO_ROOTS = (Path("/videos"),)
DEFAULT_SONG_ROOTS = (Path("/songs"),)


def _roots_from_env(name: str, defaults: tuple[Path, ...]) -> tuple[Path, ...]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return defaults
    return tuple(Path(p.strip()) for p in raw.split(os.pathsep) if p.strip())


def video_roots() -> tuple[Path, ...]:
    return _roots_from_env("MONTAGE_VIDEO_ROOTS", DEFAULT_VIDEO_ROOTS)


def song_roots() -> tuple[Path, ...]:
    return _roots_from_env("MONTAGE_SONG_ROOTS", DEFAULT_SONG_ROOTS)


def resolve_under_roots(raw: str, roots: tuple[Path, ...]) -> Path:
    """Resolve a path or basename so it stays inside one of the allowed roots."""
    if not raw or not str(raw).strip():
        raise ValueError("empty path")
    candidate = Path(raw)
    if not candidate.is_absolute():
        for root in roots:
            joined = (root / candidate).resolve()
            if _is_under(joined, root.resolve()) and joined.is_file():
                return joined
        raise FileNotFoundError(f"not found under allowed roots: {raw}")
    resolved = candidate.resolve()
    for root in roots:
        if _is_under(resolved, root.resolve()) and resolved.is_file():
            return resolved
    raise PermissionError(f"path escapes allowed roots: {raw}")


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def list_media_files(roots: tuple[Path, ...], suffixes: tuple[str, ...]) -> list[tuple[str, Path, int]]:
    out: list[tuple[str, Path, int]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix.lower() not in suffixes:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            out.append((p.name, p, size))
    out.sort(key=lambda row: row[0].lower())
    return out


def link_or_copy(src: Path, dst: Path) -> None:
    """Prefer symlink (zero-copy across bind mounts), then hardlink, then copy."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        dst.symlink_to(src)
        return
    except OSError:
        pass
    try:
        os.link(src, dst)
        return
    except OSError:
        pass
    shutil.copy2(src, dst)
