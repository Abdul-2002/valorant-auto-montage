"""Run kill_grouping tests without pytest (Docker image lacks pytest)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tests.test_kill_grouping as mod


def main() -> int:
    failed = 0
    for name in sorted(n for n in dir(mod) if n.startswith("test_")):
        try:
            getattr(mod, name)()
            print("OK", name, flush=True)
        except Exception as exc:
            failed += 1
            print("FAIL", name, repr(exc), flush=True)
    print("ALL_OK" if not failed else f"FAILED {failed}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
