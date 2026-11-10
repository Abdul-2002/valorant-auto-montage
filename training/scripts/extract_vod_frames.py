"""Extract sparse stills from VODs into a raw annotation folder.

READ-ONLY on source videos:
- Never opens a VOD for write
- Never overwrites, renames, moves, or deletes anything under --src
- All outputs go under --dest only (default: E:\\VALORANT\\_training_raw\\vod_frames)

Uses ffmpeg (imageio-ffmpeg build) to sample frames. Idempotent via .frames_ok.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}


def _resolve_ffmpeg() -> str:
    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and Path(bundled).is_file():
            return bundled
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise SystemExit("ffmpeg not found; pip install imageio-ffmpeg")


def _slug(name: str) -> str:
    base = Path(name).stem
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_")
    return cleaned[:120] or "video"


def _assert_dest_outside_src(src: Path, dest: Path) -> None:
    src_r = src.resolve()
    dest_r = dest.resolve()
    try:
        dest_r.relative_to(src_r)
    except ValueError:
        return
    # dest is inside src — only allow the dedicated _training_raw subtree
    parts = {p.lower() for p in dest_r.parts}
    if "_training_raw" not in parts:
        raise SystemExit(
            f"Refusing dest inside src unless under _training_raw: dest={dest_r}"
        )


def _extract_one(
    ffmpeg: str,
    video: Path,
    dest_root: Path,
    interval_sec: float,
    min_bytes: int,
) -> tuple[str, int]:
    out_dir = dest_root / _slug(video.name)
    marker = out_dir / ".frames_ok"
    if marker.is_file():
        n = sum(1 for _ in out_dir.glob("*.jpg"))
        if n > 0:
            return "skip", n
        # Bad prior run (0 frames) — clear only the output dir, never the source
        shutil.rmtree(out_dir)

    if video.stat().st_size < min_bytes:
        return "tiny", 0

    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "f_%06d.jpg")
    # Input is read-only (-i only). Outputs are ONLY under out_dir.
    # Game DVR files often emit h264 warnings; keep going and judge by jpg count.
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-fflags",
        "+genpts+discardcorrupt",
        "-err_detect",
        "ignore_err",
        "-i",
        str(video),
        "-vf",
        f"fps=1/{interval_sec}",
        "-q:v",
        "2",
        pattern,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    saved = sum(1 for _ in out_dir.glob("*.jpg"))
    if saved <= 0:
        err = (proc.stderr or proc.stdout or "").strip()[:200]
        return f"empty:{err or f'rc={proc.returncode}'}", 0

    marker.write_text(
        f"source={video}\ninterval_sec={interval_sec}\nframes={saved}\n"
        f"read_only_source=1\nffmpeg_rc={proc.returncode}\n",
        encoding="utf-8",
    )
    return "ok", saved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=Path(r"E:\VALORANT"))
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path(r"E:\VALORANT\_training_raw\vod_frames"),
    )
    parser.add_argument("--interval-sec", type=float, default=2.0)
    parser.add_argument("--min-mb", type=float, default=5.0)
    parser.add_argument("--limit", type=int, default=0, help="Max videos (0=all)")
    args = parser.parse_args()

    src: Path = args.src
    dest: Path = args.dest
    if not src.is_dir():
        print(f"FAIL src missing: {src}", flush=True)
        return 1

    _assert_dest_outside_src(src, dest)
    dest.mkdir(parents=True, exist_ok=True)

    videos = sorted(
        p for p in src.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    )
    if args.limit > 0:
        videos = videos[: args.limit]

    ffmpeg = _resolve_ffmpeg()
    min_bytes = int(args.min_mb * 1024 * 1024)
    print(
        f"read_only_src={src} dest={dest} videos={len(videos)} "
        f"interval={args.interval_sec}s ffmpeg={ffmpeg}",
        flush=True,
    )

    totals: dict[str, int] = {"ok": 0, "skip": 0, "tiny": 0, "empty": 0, "frames": 0}
    for i, video in enumerate(videos, start=1):
        # Defense: never pass source as an output path
        if dest.resolve() in video.resolve().parents:
            print(f"[{i}/{len(videos)}] refuse_nested {video.name}", flush=True)
            continue
        status, n = _extract_one(ffmpeg, video, dest, args.interval_sec, min_bytes)
        key = status.split(":", 1)[0]
        totals[key] = totals.get(key, 0) + 1
        totals["frames"] += n
        print(f"[{i}/{len(videos)}] {status} frames={n} {video.name}", flush=True)

    print(
        "DONE "
        + " ".join(f"{k}={v}" for k, v in totals.items() if k != "frames")
        + f" frames={totals['frames']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
