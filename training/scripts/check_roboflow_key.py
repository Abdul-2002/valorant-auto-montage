"""Presence-only check for ROBOFLOW_API_KEY / ROBOFLOW_KEY. Never prints the value."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    env_path = REPO / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


def main() -> int:
    _load_dotenv()
    key = (os.environ.get("ROBOFLOW_API_KEY") or os.environ.get("ROBOFLOW_KEY") or "").strip()
    print("key_present", bool(key))
    print("key_len", len(key))
    return 0 if key else 1


if __name__ == "__main__":
    sys.exit(main())
