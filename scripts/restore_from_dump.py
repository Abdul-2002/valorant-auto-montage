#!/usr/bin/env python3
"""Restore missing source files from codebase_dump.txt.

The dump inlines 90 files from the original Linux repo. The Windows copy only
has ~10 of them. This script extracts every inlined file that does NOT already
exist on disk (existing local files are newer and must not be overwritten).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DUMP = ROOT / "codebase_dump.txt"

SEP = "=" * 80


def parse_dump(text: str) -> dict[str, str]:
    """Return {relative_path: file_content} for every inlined file."""
    lines = text.splitlines()
    files: dict[str, str] = {}
    i = 0
    current_path: str | None = None
    content_start = 0

    while i < len(lines):
        if (
            lines[i] == SEP
            and i + 2 < len(lines)
            and lines[i + 1].startswith("FILE: ")
            and lines[i + 2] == SEP
        ):
            if current_path is not None:
                files[current_path] = "\n".join(lines[content_start:i]).rstrip() + "\n"
            current_path = lines[i + 1][len("FILE: "):].strip()
            content_start = i + 3
            i += 3
            continue
        i += 1

    if current_path is not None:
        files[current_path] = "\n".join(lines[content_start:]).rstrip() + "\n"
    return files


def main() -> int:
    if not DUMP.exists():
        print(f"dump not found: {DUMP}", file=sys.stderr)
        return 1

    files = parse_dump(DUMP.read_text(encoding="utf-8", errors="replace"))
    print(f"inlined files in dump: {len(files)}")

    written, skipped = [], []
    for rel, content in files.items():
        # Reject anything escaping the repo root.
        if re.search(r"(^/|^[A-Za-z]:|\.\.)", rel):
            print(f"  !! suspicious path skipped: {rel}")
            continue
        dest = ROOT / Path(rel)
        if dest.exists():
            skipped.append(rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8", newline="\n")
        written.append(rel)

    print(f"written: {len(written)}, kept existing: {len(skipped)}")
    for rel in sorted(written):
        print(f"  + {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
