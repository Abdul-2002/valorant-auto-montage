#!/usr/bin/env python3
"""Objective style comparison: pipeline output vs reference montages.

Measures signals that define the reference look (reference/fiverr-rafialihsan)
so "similar" is a number, not a vibe:

- hard cuts per minute   (scene-detection; motion transitions stay invisible)
- mean saturation        (signalstats SATAVG; the reference grades hard)
- mean luma              (signalstats YAVG)
- white flashes per min  (sampled YAVG >= threshold; flash transitions/hits)

Usage:
    python scripts/compare_to_reference.py \
        --target artifacts/run22/outputs/montage_16x9.mp4 \
        --refs reference/fiverr-rafialihsan
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.io.audio_loader import resolve_ffmpeg_exe

_SCENE_THRESHOLD = 0.35
_FLASH_LUMA = 200.0
_GRADE_SAMPLE_EVERY_N_FRAMES = 24

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_STAT_RE = re.compile(r"lavfi\.signalstats\.(YAVG|SATAVG)=([0-9.]+)")


def _run_ffmpeg(args: list[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    return proc.stderr


def _duration_sec(ffmpeg: str, path: Path) -> float:
    m = _DURATION_RE.search(_run_ffmpeg([ffmpeg, "-hide_banner", "-i", str(path)]))
    if not m:
        raise RuntimeError(f"no duration in ffmpeg output for {path}")
    hh, mm, ss = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return hh * 3600 + mm * 60 + ss


def _scene_cuts(ffmpeg: str, path: Path) -> int:
    out = _run_ffmpeg(
        [ffmpeg, "-hide_banner", "-i", str(path), "-vf", f"select='gt(scene,{_SCENE_THRESHOLD})',showinfo", "-f", "null", "-"]
    )
    return out.count("Parsed_showinfo")


def _grade_stats(ffmpeg: str, path: Path) -> tuple[float, float, int]:
    """(mean saturation, mean luma, white-flash samples) over sampled frames."""
    out = _run_ffmpeg(
        [
            ffmpeg, "-hide_banner", "-i", str(path),
            "-vf", f"select='not(mod(n\\,{_GRADE_SAMPLE_EVERY_N_FRAMES}))',signalstats,metadata=print",
            "-f", "null", "-",
        ]
    )
    sats: list[float] = []
    lumas: list[float] = []
    for key, val in _STAT_RE.findall(out):
        (lumas if key == "YAVG" else sats).append(float(val))
    if not sats or not lumas:
        raise RuntimeError(f"no signalstats parsed for {path}")
    flashes = sum(1 for y in lumas if y >= _FLASH_LUMA)
    return statistics.fmean(sats), statistics.fmean(lumas), flashes


def measure_video(ffmpeg: str, path: Path) -> dict[str, float | str]:
    dur = _duration_sec(ffmpeg, path)
    cuts = _scene_cuts(ffmpeg, path)
    sat, luma, flashes = _grade_stats(ffmpeg, path)
    minutes = max(dur / 60.0, 1e-9)
    sampled_minutes = minutes  # flash count is over the same sampled span
    return {
        "file": path.name,
        "duration_sec": round(dur, 2),
        "cuts_per_min": round(cuts / minutes, 1),
        "saturation_avg": round(sat, 1),
        "luma_avg": round(luma, 1),
        "white_flashes_per_min": round(flashes / sampled_minutes, 1),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Compare pipeline output style against reference montages")
    p.add_argument("--target", type=Path, required=True, help="Pipeline output mp4")
    p.add_argument("--refs", type=Path, required=True, help="Folder with reference mp4s")
    p.add_argument("--report", type=Path, default=None, help="JSON report path (default: <target>.style_compare.json)")
    args = p.parse_args()

    if not args.target.is_file():
        print(f"Target not found: {args.target}", file=sys.stderr)
        return 1
    refs = sorted(args.refs.glob("*.mp4"))
    if not refs:
        print(f"No reference mp4s in {args.refs}", file=sys.stderr)
        return 1

    ffmpeg = resolve_ffmpeg_exe()
    ref_rows = []
    for ref in refs:
        row = measure_video(ffmpeg, ref)
        ref_rows.append(row)
        print(f"ref  {row['file']:<32} cuts/min={row['cuts_per_min']:<6} sat={row['saturation_avg']:<6} luma={row['luma_avg']:<6} flashes/min={row['white_flashes_per_min']}", flush=True)

    target = measure_video(ffmpeg, args.target)
    median = {
        "cuts_per_min": statistics.median(float(r["cuts_per_min"]) for r in ref_rows),
        "saturation_avg": statistics.median(float(r["saturation_avg"]) for r in ref_rows),
        "luma_avg": statistics.median(float(r["luma_avg"]) for r in ref_rows),
        "white_flashes_per_min": statistics.median(float(r["white_flashes_per_min"]) for r in ref_rows),
    }
    deltas = {k: round(float(target[k]) - median[k], 1) for k in median}

    print(f"\ntgt  {target['file']:<32} cuts/min={target['cuts_per_min']:<6} sat={target['saturation_avg']:<6} luma={target['luma_avg']:<6} flashes/min={target['white_flashes_per_min']}")
    print(f"ref-median {'':<30} cuts/min={median['cuts_per_min']:<6} sat={median['saturation_avg']:<6} luma={median['luma_avg']:<6} flashes/min={median['white_flashes_per_min']}")
    print(f"delta {'':<35} cuts/min={deltas['cuts_per_min']:+<6} sat={deltas['saturation_avg']:+<6} luma={deltas['luma_avg']:+<6} flashes/min={deltas['white_flashes_per_min']:+}")

    report = {"target": target, "reference_median": median, "delta": deltas, "references": ref_rows}
    report_path = args.report or args.target.with_suffix(".style_compare.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
