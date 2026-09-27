#!/usr/bin/env python3
"""Export per-kill review clips from a highlights JSON (no montage)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.io.audio_loader import resolve_ffmpeg_exe


def cut_clip(
    *,
    ffmpeg: str,
    video: Path,
    timestamp_sec: float,
    pre_sec: float,
    post_sec: float,
    out_path: Path,
) -> bool:
    start = max(0.0, float(timestamp_sec) - float(pre_sec))
    dur = float(pre_sec) + float(post_sec)
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(video),
        "-t",
        f"{dur:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 1000


def main() -> int:
    p = argparse.ArgumentParser(description="Export kill review clips")
    p.add_argument("--highlights", type=Path, required=True)
    p.add_argument("--video", type=Path, nargs="+", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--pre", type=float, default=1.5)
    p.add_argument("--post", type=float, default=1.5)
    args = p.parse_args()

    videos = [v.resolve() for v in args.video]
    for v in videos:
        if not v.is_file():
            print(f"Missing video: {v}", file=sys.stderr)
            return 1

    data = json.loads(args.highlights.read_text(encoding="utf-8"))
    events = list(data.get("highlights") or data.get("accepted") or [])
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = resolve_ffmpeg_exe()

    manifest: list[dict] = []
    for i, ev in enumerate(events):
        vid_i = int(ev["video_index"])
        ts = float(ev["timestamp_sec"])
        if vid_i < 0 or vid_i >= len(videos):
            print(f"skip bad video_index={vid_i}", file=sys.stderr)
            continue
        name = f"kill_{i:03d}_v{vid_i}_t{ts:07.2f}.mp4"
        out_path = out_dir / name
        ok = cut_clip(
            ffmpeg=ffmpeg,
            video=videos[vid_i],
            timestamp_sec=ts,
            pre_sec=args.pre,
            post_sec=args.post,
            out_path=out_path,
        )
        entry = {
            "index": i,
            "file": name,
            "video_index": vid_i,
            "timestamp_sec": ts,
            "event_type": ev.get("event_type"),
            "score": ev.get("score"),
            "source": ev.get("source"),
            "ok": ok,
            "window": [max(0.0, ts - args.pre), ts + args.post],
        }
        manifest.append(entry)
        status = "OK" if ok else "FAIL"
        print(f"{status} {name}", flush=True)

    (out_dir / "manifest.json").write_text(
        json.dumps(
            {
                "pre_sec": args.pre,
                "post_sec": args.post,
                "highlights": str(args.highlights.resolve()),
                "videos": [str(v) for v in videos],
                "clips": manifest,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    ok_n = sum(1 for m in manifest if m["ok"])
    print(f"Done: {ok_n}/{len(manifest)} clips -> {out_dir}", flush=True)
    return 0 if ok_n == len(manifest) else 2


if __name__ == "__main__":
    raise SystemExit(main())
