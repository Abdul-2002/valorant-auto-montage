"""Tiny test runner when pytest is not installed in the image."""
from __future__ import annotations

import importlib.util
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    failed = 0
    for rel in ("tests/test_kill_grouping.py", "tests/test_bar_layout.py", "tests/test_flow_scoring.py"):
        path = ROOT / rel
        spec = importlib.util.spec_from_file_location(path.stem, path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for name in sorted(n for n in dir(mod) if n.startswith("test_")):
            try:
                getattr(mod, name)()
                print("ok", name)
            except Exception:
                failed += 1
                print("FAIL", name)
                traceback.print_exc()
    print("failed", failed)
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
