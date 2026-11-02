from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.app.media_paths import link_or_copy, resolve_under_roots


def main() -> int:
    td = Path(tempfile.mkdtemp())
    root = td / "videos"
    root.mkdir()
    f = root / "a.mp4"
    f.write_bytes(b"x")
    assert resolve_under_roots("a.mp4", (root,)) == f.resolve()
    try:
        resolve_under_roots(str(td / "x.mp4"), (root,))
        raise AssertionError("should reject escape")
    except PermissionError:
        pass
    dst = td / "out" / "b.mp4"
    link_or_copy(f, dst)
    assert dst.read_bytes() == b"x"
    print("ok media_paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
