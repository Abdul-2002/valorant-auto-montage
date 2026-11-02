from pathlib import Path

import pytest

from src.app.media_paths import link_or_copy, resolve_under_roots


def test_should_resolve_basename_under_allowed_root(tmp_path: Path) -> None:
    root = tmp_path / "videos"
    root.mkdir()
    clip = root / "ace.mp4"
    clip.write_bytes(b"x")
    assert resolve_under_roots("ace.mp4", (root,)) == clip.resolve()


def test_should_reject_path_outside_allowed_roots(tmp_path: Path) -> None:
    root = tmp_path / "videos"
    root.mkdir()
    outsider = tmp_path / "secret.mp4"
    outsider.write_bytes(b"x")
    with pytest.raises(PermissionError):
        resolve_under_roots(str(outsider), (root,))


def test_should_symlink_when_possible(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    src.write_bytes(b"abc")
    dst = tmp_path / "linked" / "dst.mp4"
    link_or_copy(src, dst)
    assert dst.exists()
    assert dst.read_bytes() == b"abc"
