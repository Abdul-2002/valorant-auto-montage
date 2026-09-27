#!/usr/bin/env python3
"""N-way kill-detector bakeoff: YOLO weights + Gemini + local VLMs.

Phases
------
1. DETECT — run each YOLO weight and (optionally) Gemini video on the same VODs.
2. LOAD  — try to load every local VLM; record OOM / import / download failures.
3. JUDGE — for each VLM that loads (+ Gemini clip verify), score run18 kill clips.

Outputs land under artifacts/bakeoff_nway/.
"""
from __future__ import annotations

import argparse
import gc
import json
import logging
import os
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bakeoff")

# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

YOLO_RUNS: list[dict[str, Any]] = [
    {
        "id": "yolo_auto_gaming",
        "detector": "auto_gaming_yolo",
        "cfg": {
            "model_path": "models/auto_gaming_valorant.pt",
            "confidence_threshold": 0.5,
            "region": [0.0, 0.0, 1.0, 1.0],
            "sample_fps": 3,
            "presence_conf": 0.3,
            "reemit_guard_sec": 1.5,
            "killfeed_latency_sec": 0.1,
            "refine_full_fps": True,
        },
    },
    {
        "id": "yolo_killfeed_yolo11n",
        "detector": "valorant_yolo",
        "cfg": {
            "model_path": "models/valorant_killfeed_yolo11n.pt",
            "confidence_threshold": 0.5,
            "region": [0.65, 0.0, 1.0, 0.15],
            "sample_fps": 3,
        },
    },
    {
        "id": "yolo_best_kill_only",
        "detector": "auto_gaming_yolo",
        "cfg": {
            "model_path": "models/best_kill_only.pt",
            "confidence_threshold": 0.5,
            "region": [0.0, 0.0, 1.0, 1.0],
            "sample_fps": 3,
            "presence_conf": 0.3,
            "reemit_guard_sec": 1.5,
            "killfeed_latency_sec": 0.1,
            "refine_full_fps": True,
            "class_mapping": {"kill": "kill"},
        },
    },
]

# Skip gated Gemma without token in default catalog; add via --vlm-ids if HF_TOKEN set.
VLM_CATALOG: list[dict[str, Any]] = [
    {
        "id": "qwen25_vl_3b_4bit",
        "hf_id": "Qwen/Qwen2.5-VL-3B-Instruct",
        "loader": "transformers_4bit",
        "notes": "3B VL via bitsandbytes 4bit",
    },
    {
        "id": "qwen35_4b_4bit",
        "hf_id": "Qwen/Qwen3.5-4B",
        "loader": "transformers_4bit",
        "notes": "Cached; load OK ~3.2GB peak",
    },
    {
        "id": "qwen3_vl_4b_4bit",
        "hf_id": "Qwen/Qwen3-VL-4B-Instruct",
        "loader": "transformers_4bit",
        "notes": "Cached; load OK ~2.8GB peak",
    },
    {
        "id": "molmo2_4b_4bit",
        "hf_id": "allenai/Molmo2-4B",
        "loader": "transformers_4bit",
        "notes": "Needs einops",
    },
    {
        "id": "qwen35_9b_4bit",
        "hf_id": "Qwen/Qwen3.5-9B",
        "loader": "transformers_4bit",
        "notes": "Best published VideoMME candidate",
    },
    {
        "id": "glm46v_flash_4bit",
        "hf_id": "zai-org/GLM-4.6V-Flash",
        "loader": "transformers_4bit",
        "notes": "9B flash VLM",
    },
    {
        "id": "minicpm_v45_4bit",
        "hf_id": "openbmb/MiniCPM-V-4_5",
        "loader": "transformers_4bit",
        "notes": "Likely OOM",
    },
    {
        "id": "molmo2_8b_4bit",
        "hf_id": "allenai/Molmo2-8B",
        "loader": "transformers_4bit",
        "notes": "Likely OOM",
    },
]

KILL_JUDGE_PROMPT = """You are verifying ONE candidate kill moment in a Valorant FIRST-PERSON POV clip (frames shown).

ACCEPT only if ALL are true:
- Live first-person gameplay (not death cam, spectator, scoreboard, agent select, menu)
- The POV player gets an elimination (enemy dies / kill confirm / skull / clear kill)
- Not only a teammate kill in the feed while you are dead/spectating

REJECT if ANY are true:
- Death cam / KILLED BY / combat report / SWITCH PLAYER
- Spectator UI
- No elimination occurs
- Unclear / cannot tell

Reply with a single JSON object only. Do not copy this instruction. Fields:
accept (boolean), confidence (number 0 to 1), reason (one short sentence describing what you see).
"""


@dataclass
class LoadResult:
    id: str
    hf_id: str
    ok: bool
    error: str = ""
    peak_vram_mb: float | None = None
    load_sec: float | None = None
    notes: str = ""


@dataclass
class JudgeResult:
    model_id: str
    clip_file: str
    accept: bool | None
    confidence: float | None
    reason: str = ""
    error: str = ""
    latency_sec: float | None = None


@dataclass
class BakeoffReport:
    videos: list[str] = field(default_factory=list)
    yolo: dict[str, Any] = field(default_factory=dict)
    gemini_detect: dict[str, Any] = field(default_factory=dict)
    vlm_loads: list[dict[str, Any]] = field(default_factory=list)
    judges: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)


def _vram_mb() -> float | None:
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        return float(torch.cuda.max_memory_allocated() / (1024 * 1024))
    except Exception:
        return None


def _reset_cuda() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
    except Exception:
        pass


def default_videos() -> list[Path]:
    names = [
        "Valorant 2025.09.20 - 17.38.05.03.DVR.mp4",
        "Valorant 2026.09.10 - 23.40.48.02.DVR.mp4",
        "Valorant 2026.09.17 - 21.26.44.02.DVR.mp4",
        "Valorant 2026.09.23 - 23.54.38.05.DVR.mp4",
    ]
    out = [ROOT / n for n in names]
    missing = [p for p in out if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing VODs: {missing}")
    return out


# ---------------------------------------------------------------------------
# Phase 1 — YOLO / Gemini detect
# ---------------------------------------------------------------------------


def run_yolo_detect(out_dir: Path, videos: list[Path]) -> dict[str, Any]:
    from src.detection.base import DetectionContext
    from src.detection.registry import get_detector

    assets = (ROOT / "assets").resolve()
    results: dict[str, Any] = {}
    for spec in YOLO_RUNS:
        rid = spec["id"]
        det_name = spec["detector"]
        cfg = dict(spec["cfg"])
        log.info("DETECT %s via %s", rid, det_name)
        t0 = time.time()
        events: list[dict[str, Any]] = []
        err = ""
        try:
            det_cls = get_detector(det_name)
            det = det_cls.from_config(cfg)
            for idx, vp in enumerate(videos):
                ctx = DetectionContext(video_index=idx, video_path=vp, assets_dir=assets, config={})
                events.extend(det.detect(ctx))
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            log.exception("DETECT failed %s", rid)
        elapsed = time.time() - t0
        by_vid: dict[str, int] = {}
        for e in events:
            k = str(e.get("video_index"))
            by_vid[k] = by_vid.get(k, 0) + 1
        payload = {
            "id": rid,
            "detector": det_name,
            "model_path": cfg.get("model_path"),
            "count": len(events),
            "by_video": by_vid,
            "elapsed_sec": round(elapsed, 2),
            "error": err,
            "events": events,
        }
        (out_dir / f"detect_{rid}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        results[rid] = {k: v for k, v in payload.items() if k != "events"}
        log.info("DETECT %s -> %d events in %.1fs err=%s", rid, len(events), elapsed, err or "none")
    return results


def run_gemini_detect(out_dir: Path, videos: list[Path], enabled: bool) -> dict[str, Any]:
    if not enabled:
        return {"skipped": True, "reason": "gemini detect disabled by flag"}
    if not (os.environ.get("GEMINI_API_KEY") or "").strip():
        return {"skipped": True, "reason": "GEMINI_API_KEY missing"}

    from src.detection.base import DetectionContext
    from src.detection.registry import get_detector

    assets = (ROOT / "assets").resolve()
    log.info("DETECT gemini_video on %d VODs", len(videos))
    t0 = time.time()
    events: list[dict[str, Any]] = []
    err = ""
    try:
        det = get_detector("gemini_video").from_config(
            {"model": "gemini-2.5-flash", "min_excitement": 0.3}
        )
        for idx, vp in enumerate(videos):
            ctx = DetectionContext(
                video_index=idx,
                video_path=vp,
                assets_dir=assets,
                config={"ai_director": {"gemini": {"api_key": os.environ.get("GEMINI_API_KEY", "")}}},
            )
            events.extend(det.detect(ctx))
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        log.exception("gemini detect failed")
    elapsed = time.time() - t0
    by_vid: dict[str, int] = {}
    for e in events:
        k = str(e.get("video_index"))
        by_vid[k] = by_vid.get(k, 0) + 1
    payload = {
        "id": "gemini_video",
        "count": len(events),
        "by_video": by_vid,
        "elapsed_sec": round(elapsed, 2),
        "error": err,
        "events": events,
    }
    (out_dir / "detect_gemini_video.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {k: v for k, v in payload.items() if k != "events"}


# ---------------------------------------------------------------------------
# Phase 2 — VLM load smoke
# ---------------------------------------------------------------------------


def _import_vl_model_classes() -> list[type]:
    """Return available multimodal AutoModel classes for the installed transformers."""
    from transformers import AutoModel

    classes: list[type] = []
    for name in (
        "AutoModelForImageTextToText",
        "AutoModelForVision2Seq",
        "AutoModelForCausalLM",
    ):
        try:
            classes.append(getattr(__import__("transformers", fromlist=[name]), name))
        except Exception:
            continue
    classes.append(AutoModel)
    # Deduplicate while preserving order
    seen: set[int] = set()
    out: list[type] = []
    for cls in classes:
        i = id(cls)
        if i in seen:
            continue
        seen.add(i)
        out.append(cls)
    return out


def _try_load_transformers_4bit(hf_id: str) -> tuple[Any, Any]:
    import torch
    from transformers import AutoProcessor

    kwargs: dict[str, Any] = {
        "device_map": "auto",
        "trust_remote_code": True,
        "torch_dtype": torch.float16,
        "low_cpu_mem_usage": True,
    }
    try:
        from transformers import BitsAndBytesConfig

        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )
    except Exception:
        log.warning("bitsandbytes unavailable; attempting fp16 load for %s", hf_id)

    processor = AutoProcessor.from_pretrained(hf_id, trust_remote_code=True)
    model = None
    errors: list[str] = []
    for cls in _import_vl_model_classes():
        try:
            model = cls.from_pretrained(hf_id, **kwargs)
            break
        except Exception as exc:
            errors.append(f"{cls.__name__}: {type(exc).__name__}: {exc}")
            continue
    if model is None:
        raise RuntimeError("all loaders failed; " + " | ".join(errors[-3:]))
    model.eval()
    return model, processor


def _try_load_transformers_awq(hf_id: str) -> tuple[Any, Any]:
    import torch
    from transformers import AutoProcessor

    processor = AutoProcessor.from_pretrained(hf_id, trust_remote_code=True)
    kwargs = {
        "device_map": "cuda:0",
        "trust_remote_code": True,
        "torch_dtype": torch.float16,
    }
    model = None
    errors: list[str] = []
    for cls in _import_vl_model_classes():
        try:
            model = cls.from_pretrained(hf_id, **kwargs)
            break
        except Exception as exc:
            errors.append(f"{cls.__name__}: {type(exc).__name__}: {exc}")
            continue
    if model is None:
        raise RuntimeError("all AWQ loaders failed; " + " | ".join(errors[-3:]))
    model.eval()
    return model, processor


def smoke_load_vlms(out_dir: Path, catalog: list[dict[str, Any]], skip_download: bool) -> list[LoadResult]:
    results: list[LoadResult] = []
    for spec in catalog:
        mid = spec["id"]
        hf_id = spec["hf_id"]
        loader = spec["loader"]
        log.info("LOAD try %s (%s) via %s", mid, hf_id, loader)
        _reset_cuda()
        t0 = time.time()
        try:
            if skip_download:
                from huggingface_hub import try_to_load_from_cache

                # Soft check — still attempt from_pretrained (uses cache if present)
                pass
            if loader == "transformers_4bit":
                model, processor = _try_load_transformers_4bit(hf_id)
            elif loader == "transformers_awq":
                model, processor = _try_load_transformers_awq(hf_id)
            else:
                raise ValueError(f"unknown loader {loader}")
            peak = _vram_mb()
            # Keep a tiny forward-ready reference for later judge phase by saving nothing —
            # we unload now and reload survivors during JUDGE to free VRAM between models.
            del model, processor
            _reset_cuda()
            lr = LoadResult(
                id=mid,
                hf_id=hf_id,
                ok=True,
                peak_vram_mb=peak,
                load_sec=round(time.time() - t0, 2),
                notes=spec.get("notes", ""),
            )
            log.info("LOAD OK %s peak_vram_mb=%s in %.1fs", mid, peak, lr.load_sec or 0)
        except Exception as exc:
            lr = LoadResult(
                id=mid,
                hf_id=hf_id,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                load_sec=round(time.time() - t0, 2),
                notes=spec.get("notes", ""),
            )
            log.warning("LOAD FAIL %s: %s", mid, lr.error)
            _reset_cuda()
        results.append(lr)
        (out_dir / "vlm_load_results.json").write_text(
            json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8"
        )
    return results


# ---------------------------------------------------------------------------
# Phase 3 — Clip judge
# ---------------------------------------------------------------------------


def _frames_from_clip(clip_path: Path, max_frames: int = 6) -> list[Any]:
    import cv2
    from PIL import Image

    cap = cv2.VideoCapture(str(clip_path))
    if not cap.isOpened():
        return []
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    idxs = [0]
    if total > 1:
        step = max(1, total // max_frames)
        idxs = list(range(0, total, step))[:max_frames]
    frames: list[Any] = []
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(i))
        ok, frame = cap.read()
        if not ok:
            continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        # Cap resolution to control visual tokens on 8GB.
        h, w = rgb.shape[:2]
        scale = min(1.0, 768.0 / max(h, w))
        if scale < 1.0:
            rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)))
        frames.append(Image.fromarray(rgb))
    cap.release()
    return frames


def _parse_json_blob(text: str) -> dict[str, Any]:
    text = text.strip()
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()
    if "```" in text:
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if "{" in part:
                text = part
                break
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"no JSON object in: {text[:200]}")
    return json.loads(text[start : end + 1])


def judge_clip_transformers(model: Any, processor: Any, frames: list[Any]) -> dict[str, Any]:
    import torch

    content: list[dict[str, Any]] = [{"type": "text", "text": KILL_JUDGE_PROMPT}]
    for fr in frames:
        content.append({"type": "image", "image": fr})
    messages = [{"role": "user", "content": content}]
    try:
        try:
            text = processor.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        except TypeError:
            text = processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        inputs = processor(text=[text], images=frames, return_tensors="pt", padding=True)
    except Exception:
        inputs = processor(images=frames, text=KILL_JUDGE_PROMPT, return_tensors="pt")
    device = getattr(model, "device", None)
    if device is None:
        try:
            device = next(model.parameters()).device
        except Exception:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    inputs = {k: v.to(device) if hasattr(v, "to") else v for k, v in inputs.items()}
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=160, do_sample=False)
    try:
        prompt_len = int(inputs["input_ids"].shape[-1])
        decoded = processor.batch_decode(out[:, prompt_len:], skip_special_tokens=True)[0]
    except Exception:
        decoded = processor.batch_decode(out, skip_special_tokens=True)[0]
    return _parse_json_blob(decoded)


def judge_with_gemini_clips(clips_dir: Path, manifest: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    if not (os.environ.get("GEMINI_API_KEY") or "").strip():
        return {"skipped": True, "reason": "GEMINI_API_KEY missing"}

    from src.detection.base import DetectionContext
    from src.detection.registry import get_detector

    # Reuse gemini_kill_verify against original video+timestamp from manifest clips.
    videos = [Path(v) for v in manifest["videos"]]
    events = []
    for c in manifest.get("clips") or []:
        events.append(
            {
                "video_index": int(c["video_index"]),
                "timestamp_sec": float(c["timestamp_sec"]),
                "score": float(c.get("score") or 0.5),
                "event_type": str(c.get("event_type") or "kill"),
            }
        )
    assets = (ROOT / "assets").resolve()
    # Process per-video by attaching candidates.
    kept: list[dict[str, Any]] = []
    rejected = 0
    err = ""
    t0 = time.time()
    try:
        det = get_detector("gemini_kill_verify").from_config(
            {
                "model": "gemini-2.5-flash-lite",
                "clip_pre_sec": 1.0,
                "clip_post_sec": 1.2,
                "min_confidence": 0.55,
            }
        )
        by_vid: dict[int, list[dict]] = {}
        for e in events:
            by_vid.setdefault(int(e["video_index"]), []).append(e)
        for idx, vp in enumerate(videos):
            cands = by_vid.get(idx) or []
            if not cands:
                continue
            ctx = DetectionContext(
                video_index=idx,
                video_path=vp,
                assets_dir=assets,
                config={
                    "ai_director": {"gemini": {"api_key": os.environ.get("GEMINI_API_KEY", "")}},
                    "_candidate_events": cands,
                },
            )
            out = det.detect(ctx)
            kept.extend(out)
            rejected += max(0, len(cands) - len(out))
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        log.exception("gemini clip judge failed")
    payload = {
        "model_id": "gemini_kill_verify",
        "accepted": len(kept),
        "rejected": rejected,
        "candidates": len(events),
        "elapsed_sec": round(time.time() - t0, 2),
        "error": err,
        "kept": kept,
    }
    (out_dir / "judge_gemini_kill_verify.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {k: v for k, v in payload.items() if k != "kept"}


def judge_with_local_vlm(
    *,
    load: LoadResult,
    catalog_entry: dict[str, Any],
    clips_dir: Path,
    manifest: dict[str, Any],
    out_dir: Path,
    max_clips: int,
) -> dict[str, Any]:
    _reset_cuda()
    t_load = time.time()
    loader = catalog_entry["loader"]
    if loader == "transformers_4bit":
        model, processor = _try_load_transformers_4bit(load.hf_id)
    else:
        model, processor = _try_load_transformers_awq(load.hf_id)
    load_sec = time.time() - t_load
    peak = _vram_mb()

    clips = list(manifest.get("clips") or [])[: max(1, max_clips)]
    judgments: list[dict[str, Any]] = []
    accept_n = 0
    for c in clips:
        clip_path = clips_dir / c["file"]
        t0 = time.time()
        jr: dict[str, Any] = {
            "clip_file": c["file"],
            "video_index": c.get("video_index"),
            "timestamp_sec": c.get("timestamp_sec"),
        }
        try:
            frames = _frames_from_clip(clip_path)
            if not frames:
                raise RuntimeError("no frames decoded")
            parsed = judge_clip_transformers(model, processor, frames)
            jr["accept"] = bool(parsed.get("accept"))
            jr["confidence"] = float(parsed.get("confidence") or 0.0)
            jr["reason"] = str(parsed.get("reason") or "")[:240]
            if jr["accept"]:
                accept_n += 1
        except Exception as exc:
            jr["accept"] = None
            jr["error"] = f"{type(exc).__name__}: {exc}"
            jr["traceback"] = traceback.format_exc()[-800:]
        jr["latency_sec"] = round(time.time() - t0, 2)
        judgments.append(jr)
        log.info(
            "JUDGE %s %s accept=%s err=%s",
            load.id,
            c["file"],
            jr.get("accept"),
            jr.get("error", "")[:80],
        )

    del model, processor
    _reset_cuda()
    payload = {
        "model_id": load.id,
        "hf_id": load.hf_id,
        "load_sec": round(load_sec, 2),
        "peak_vram_mb": peak,
        "candidates": len(clips),
        "accepted": accept_n,
        "rejected": sum(1 for j in judgments if j.get("accept") is False),
        "errors": sum(1 for j in judgments if j.get("accept") is None),
        "judgments": judgments,
    }
    (out_dir / f"judge_{load.id}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {k: v for k, v in payload.items() if k != "judgments"}


def build_summary(report: BakeoffReport) -> dict[str, Any]:
    yolo = report.yolo or {}
    if isinstance(yolo, dict) and yolo.get("skipped"):
        yolo_counts = {"skipped": True}
    else:
        yolo_counts = {
            k: v.get("count") for k, v in yolo.items() if isinstance(v, dict) and "count" in v
        }
    load_rows = [x for x in (report.vlm_loads or []) if isinstance(x, dict) and "id" in x]
    loads_ok = [x["id"] for x in load_rows if x.get("ok")]
    loads_fail = [
        {"id": x["id"], "error": (x.get("error") or "")[:160]} for x in load_rows if not x.get("ok")
    ]
    judge_scores = {}
    for mid, j in (report.judges or {}).items():
        if isinstance(j, dict) and "accepted" in j:
            judge_scores[mid] = {
                "accepted": j.get("accepted"),
                "rejected": j.get("rejected"),
                "candidates": j.get("candidates"),
                "errors": j.get("errors"),
            }
    return {
        "yolo_event_counts": yolo_counts,
        "gemini_detect": report.gemini_detect,
        "vlm_load_ok": loads_ok,
        "vlm_load_fail": loads_fail,
        "judge_scores": judge_scores,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="N-way YOLO + Gemini + local VLM bakeoff")
    p.add_argument("--out", type=Path, default=ROOT / "artifacts" / "bakeoff_nway")
    p.add_argument("--clips-dir", type=Path, default=ROOT / "artifacts" / "run18" / "kill_clips")
    p.add_argument("--skip-yolo", action="store_true")
    p.add_argument("--skip-gemini-detect", action="store_true")
    p.add_argument("--skip-gemini-judge", action="store_true")
    p.add_argument("--skip-vlm", action="store_true")
    p.add_argument("--skip-download", action="store_true", help="Only use HF cache; still attempts load")
    p.add_argument("--max-clips", type=int, default=31, help="Max run18 clips to judge per VLM")
    p.add_argument(
        "--vlm-ids",
        nargs="*",
        default=None,
        help="Optional subset of VLM catalog ids to attempt",
    )
    args = p.parse_args()

    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    videos = default_videos()
    report = BakeoffReport(videos=[str(v) for v in videos])

    if not args.skip_yolo:
        report.yolo = run_yolo_detect(out_dir, videos)
    else:
        # Rehydrate prior YOLO detect summaries if present.
        prior: dict[str, Any] = {}
        for pth in out_dir.glob("detect_yolo_*.json"):
            try:
                blob = json.loads(pth.read_text(encoding="utf-8"))
                prior[str(blob.get("id") or pth.stem)] = {
                    k: v for k, v in blob.items() if k != "events"
                }
            except Exception:
                continue
        report.yolo = prior or {"skipped": True}

    gemini_detect_path = out_dir / "detect_gemini_video.json"
    if not args.skip_gemini_detect:
        report.gemini_detect = run_gemini_detect(out_dir, videos, enabled=True)
    elif gemini_detect_path.is_file():
        blob = json.loads(gemini_detect_path.read_text(encoding="utf-8"))
        report.gemini_detect = {k: v for k, v in blob.items() if k != "events"}
    else:
        report.gemini_detect = {"skipped": True, "reason": "gemini detect disabled"}

    catalog = VLM_CATALOG
    if args.vlm_ids:
        wanted = set(args.vlm_ids)
        catalog = [c for c in VLM_CATALOG if c["id"] in wanted]

    loads: list[LoadResult] = []
    if not args.skip_vlm:
        loads = smoke_load_vlms(out_dir, catalog, skip_download=args.skip_download)
        report.vlm_loads = [asdict(x) for x in loads]
    else:
        report.vlm_loads = [{"skipped": True}]

    manifest_path = args.clips_dir / "manifest.json"
    if not manifest_path.is_file():
        log.error("missing clip manifest: %s", manifest_path)
        report.summary = build_summary(report)
        (out_dir / "report.json").write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    judges: dict[str, Any] = {}
    if not args.skip_gemini_judge:
        judges["gemini_kill_verify"] = judge_with_gemini_clips(args.clips_dir, manifest, out_dir)

    cat_by_id = {c["id"]: c for c in catalog}
    for lr in loads:
        if not lr.ok:
            continue
        try:
            judges[lr.id] = judge_with_local_vlm(
                load=lr,
                catalog_entry=cat_by_id[lr.id],
                clips_dir=args.clips_dir,
                manifest=manifest,
                out_dir=out_dir,
                max_clips=int(args.max_clips),
            )
        except Exception as exc:
            judges[lr.id] = {"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-1200:]}
            log.exception("judge failed for %s", lr.id)
            _reset_cuda()

    report.judges = judges
    report.summary = build_summary(report)
    (out_dir / "report.json").write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    print(json.dumps(report.summary, indent=2))
    log.info("Bakeoff complete -> %s", out_dir / "report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
