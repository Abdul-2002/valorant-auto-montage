#!/usr/bin/env python3
"""Export per-method kill clips + concatenated review MP4s for the bakeoff."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.export_kill_clips import cut_clip
from src.io.audio_loader import resolve_ffmpeg_exe

VIDEOS = [
    ROOT / "Valorant 2025.09.20 - 17.38.05.03.DVR.mp4",
    ROOT / "Valorant 2026.09.10 - 23.40.48.02.DVR.mp4",
    ROOT / "Valorant 2026.09.17 - 21.26.44.02.DVR.mp4",
    ROOT / "Valorant 2026.09.23 - 23.54.38.05.DVR.mp4",
]
OUT_ROOT = ROOT / "artifacts" / "bakeoff_nway" / "final"
PRE, POST = 1.5, 1.5


def write_highlights(events: list[dict], path: Path) -> None:
    path.write_text(json.dumps({"highlights": events}, indent=2), encoding="utf-8")


def export_events(name: str, events: list[dict], ffmpeg: str) -> Path:
    out_dir = OUT_ROOT / name / "kill_clips"
    out_dir.mkdir(parents=True, exist_ok=True)
    # clear old clips
    for old in out_dir.glob("*.mp4"):
        old.unlink()
    manifest: list[dict] = []
    for i, ev in enumerate(sorted(events, key=lambda e: (int(e["video_index"]), float(e["timestamp_sec"])))):
        vid_i = int(ev["video_index"])
        ts = float(ev["timestamp_sec"])
        if vid_i < 0 or vid_i >= len(VIDEOS):
            continue
        fname = f"kill_{i:03d}_v{vid_i}_t{ts:07.2f}.mp4"
        out_path = out_dir / fname
        ok = cut_clip(
            ffmpeg=ffmpeg,
            video=VIDEOS[vid_i],
            timestamp_sec=ts,
            pre_sec=PRE,
            post_sec=POST,
            out_path=out_path,
        )
        manifest.append(
            {
                "index": i,
                "file": fname,
                "video_index": vid_i,
                "timestamp_sec": ts,
                "event_type": ev.get("event_type"),
                "score": ev.get("score"),
                "source": ev.get("source"),
                "ok": ok,
            }
        )
        print(f"[{name}] {'OK' if ok else 'FAIL'} {fname}", flush=True)
    (out_dir / "manifest.json").write_text(
        json.dumps({"method": name, "pre_sec": PRE, "post_sec": POST, "clips": manifest}, indent=2),
        encoding="utf-8",
    )
    return out_dir


def concat_review(name: str, clips_dir: Path, ffmpeg: str) -> Path | None:
    clips = sorted(p for p in clips_dir.glob("kill_*.mp4") if p.stat().st_size > 1000)
    if not clips:
        print(f"[{name}] no clips to concat", flush=True)
        return None
    list_path = clips_dir / "concat_list.txt"
    list_path.write_text(
        "".join(f"file '{c.resolve().as_posix()}'\n" for c in clips),
        encoding="utf-8",
    )
    out_mp4 = OUT_ROOT / name / f"{name}_review.mp4"
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
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
        str(out_mp4),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_mp4.is_file():
        print(f"[{name}] concat FAIL: {proc.stderr[-400:]}", flush=True)
        return None
    print(f"[{name}] review -> {out_mp4} ({out_mp4.stat().st_size/1e6:.1f} MB)", flush=True)
    return out_mp4


def events_from_detect(path: Path) -> list[dict]:
    j = json.loads(path.read_text(encoding="utf-8"))
    return list(j.get("events") or [])


def events_from_gemini_baseline(path: Path) -> list[dict]:
    j = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for a in j.get("accepted") or []:
        out.append(
            {
                "video_index": int(a["video_index"]),
                "timestamp_sec": float(a["timestamp_sec"]),
                "score": float(a.get("score") or 1.0),
                "event_type": a.get("event_type") or "kill",
                "source": "gemini_kill_verify",
            }
        )
    return out


def events_from_vlm_accepts(judge_path: Path, manifest_path: Path) -> list[dict]:
    judge = json.loads(judge_path.read_text(encoding="utf-8"))
    man = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_file = {c["file"]: c for c in man.get("clips") or []}
    out = []
    for j in judge.get("judgments") or []:
        if j.get("accept") is not True:
            continue
        base = by_file.get(j.get("clip_file") or "")
        if not base:
            continue
        out.append(
            {
                "video_index": int(base["video_index"]),
                "timestamp_sec": float(base["timestamp_sec"]),
                "score": float(j.get("confidence") or 0.5),
                "event_type": "kill",
                "source": judge.get("model_id") or "vlm",
                "reason": j.get("reason"),
            }
        )
    return out


def main() -> int:
    for v in VIDEOS:
        if not v.is_file():
            print(f"missing video {v}", file=sys.stderr)
            return 1
    ffmpeg = resolve_ffmpeg_exe()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    bake = ROOT / "artifacts" / "bakeoff_nway"
    run18_man = ROOT / "artifacts" / "run18" / "kill_clips" / "manifest.json"

    jobs: list[tuple[str, list[dict]]] = []

    for det_id, fname in [
        ("yolo_auto_gaming", "detect_yolo_auto_gaming.json"),
        ("yolo_killfeed_yolo11n", "detect_yolo_killfeed_yolo11n.json"),
        ("yolo_best_kill_only", "detect_yolo_best_kill_only.json"),
    ]:
        jobs.append((det_id, events_from_detect(bake / fname)))

    gemini = events_from_gemini_baseline(bake / "judge_gemini_run17_baseline.json")
    jobs.append(("gemini_verify_accepted", gemini))

    for vlm_name, jpath in [
        ("vlm_qwen35_4b_accepted", bake / "judge_qwen35_4b_4bit.json"),
        ("vlm_qwen25_vl_3b_accepted", bake / "judge_qwen25_vl_3b_4bit.json"),
        ("vlm_qwen3_vl_4b_accepted", bake / "judge_qwen3_vl_4b_4bit.json"),
    ]:
        jobs.append((vlm_name, events_from_vlm_accepts(jpath, run18_man)))

    index: dict[str, dict] = {}
    for name, events in jobs:
        hl_path = OUT_ROOT / name / "highlights.json"
        hl_path.parent.mkdir(parents=True, exist_ok=True)
        write_highlights(events, hl_path)
        print(f"\n=== {name}: {len(events)} events ===", flush=True)
        if not events:
            index[name] = {"events": 0, "clips_dir": None, "review": None}
            continue
        clips_dir = export_events(name, events, ffmpeg)
        review = concat_review(name, clips_dir, ffmpeg)
        index[name] = {
            "events": len(events),
            "clips_dir": str(clips_dir),
            "review": str(review) if review else None,
            "highlights": str(hl_path),
        }

    index_path = OUT_ROOT / "INDEX.json"
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"\nINDEX -> {index_path}", flush=True)
    for k, v in index.items():
        print(f"  {k}: events={v['events']} review={v.get('review')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
