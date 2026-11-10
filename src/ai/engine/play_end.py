"""Gameplay play-end boundary: hard post-kill caps beat music-bar padding.

After the last validated kill, the source window must end at the earliest of:
recipe cap, player death/spectator (minus pad), round-end, or an optional Gemini
arbiter. Output slots are shortened to match and later clips are repacked so the
montage bed stays contiguous.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Sequence

import cv2

from src.ai.schema import ScriptClip
from src.config.effect_models import PlayEndEffectConfig
from src.detection.kill_frame_refine import is_death_or_spectator_frame

logger = logging.getLogger(__name__)

# Never cut so tight that the kill frame itself is dropped.
_MIN_POST_SEC: float = 0.05

# Public alias used by tests and call sites.
PlayEndConfig = PlayEndEffectConfig


def recipe_max_post_sec(recipe: str, cfg: PlayEndConfig) -> float:
    key = str(recipe or "clean").lower()
    if key == "punch":
        return float(cfg.punch_max_post_sec)
    if key == "cinematic":
        return float(cfg.cinematic_max_post_sec)
    if key == "slow":
        return float(cfg.slow_max_post_sec)
    return float(cfg.clean_max_post_sec)


def resolve_play_end_sec(
    *,
    last_kill_sec: float,
    recipe: str,
    cfg: PlayEndConfig,
    death_sec: float | None = None,
    round_end_sec: float | None = None,
    video_end_sec: float | None = None,
    gemini_end_sec: float | None = None,
) -> float:
    """Earliest legal source end after ``last_kill_sec``."""
    last = float(last_kill_sec)
    floor = last + _MIN_POST_SEC
    candidates = [last + recipe_max_post_sec(recipe, cfg)]
    if death_sec is not None and float(death_sec) > last:
        candidates.append(float(death_sec) - float(cfg.death_pad_sec))
    if round_end_sec is not None and float(round_end_sec) > last:
        candidates.append(float(round_end_sec))
    if gemini_end_sec is not None and float(gemini_end_sec) > last:
        candidates.append(float(gemini_end_sec))
    end = min(candidates)
    end = max(end, floor)
    if video_end_sec is not None and float(video_end_sec) > 0:
        end = min(end, float(video_end_sec))
    return float(end)


def crosses_death_break(prev_kill_sec: float, next_kill_sec: float, breaks: Sequence[float]) -> bool:
    """True when a death/spectator break sits strictly after prev and at/before next."""
    lo, hi = float(prev_kill_sec), float(next_kill_sec)
    return any(lo < float(b) <= hi for b in breaks)


def apply_source_and_output_end(
    clip: ScriptClip,
    *,
    play_end_src: float,
    cfg: PlayEndConfig,
) -> ScriptClip:
    """Clamp source end and shrink the output tail after the last kill accent."""
    last_kill = float(clip.kill_timestamp_sec)
    end_src = max(float(clip.start_sec) + _MIN_POST_SEC, min(float(play_end_src), float(clip.end_sec)))
    out_start = float(clip.output_start_sec or 0.0)
    out_end = float(clip.output_end_sec or out_start)
    kill_outs = list(clip.kill_output_times_sec or [])
    last_kill_out = float(kill_outs[-1]) if kill_outs else max(0.0, last_kill - float(clip.start_sec))
    max_post_out = recipe_max_post_sec(clip.recipe, cfg)
    src_post = max(0.0, end_src - last_kill)
    out_post = min(max_post_out, max(_MIN_POST_SEC, src_post))
    new_out_end = min(out_end, out_start + last_kill_out + out_post)
    new_out_dur = max(_MIN_POST_SEC, new_out_end - out_start)
    knots = _trim_knots(clip.time_knots, new_out_dur=new_out_dur, src_span=max(_MIN_POST_SEC, end_src - float(clip.start_sec)))
    return clip.model_copy(
        update={
            "end_sec": end_src,
            "output_end_sec": new_out_end,
            "time_knots": knots,
        }
    )


def _trim_knots(
    knots: list[tuple[float, float]] | None,
    *,
    new_out_dur: float,
    src_span: float,
) -> list[tuple[float, float]] | None:
    if not knots:
        return [(0.0, 0.0), (new_out_dur, src_span)]
    kept = [(float(o), float(s)) for o, s in knots if float(o) <= new_out_dur + 1e-9]
    if not kept:
        kept = [(0.0, 0.0)]
    if abs(kept[-1][0] - new_out_dur) > 1e-6:
        kept.append((new_out_dur, src_span))
    else:
        kept[-1] = (new_out_dur, src_span)
    # Drop near-duplicates after clamp.
    out: list[tuple[float, float]] = [kept[0]]
    for o, s in kept[1:]:
        if o - out[-1][0] < 1e-3 or s - out[-1][1] < 1e-3:
            out[-1] = (o, s)
            continue
        out.append((o, s))
    return out


def repack_output_timeline(clips: Sequence[ScriptClip]) -> list[ScriptClip]:
    """Close holes so concat duration matches script output times.

    Relative kill/accent offsets inside each clip are preserved; absolute song
    times of later clips may leave their original bars after an earlier trim.
    """
    if not clips:
        return []
    packed: list[ScriptClip] = []
    cursor = float(clips[0].output_start_sec or 0.0)
    for clip in clips:
        old_start = float(clip.output_start_sec or 0.0)
        old_end = float(clip.output_end_sec or old_start)
        dur = max(_MIN_POST_SEC, old_end - old_start)
        new_start = cursor
        new_end = cursor + dur
        packed.append(clip.model_copy(update={"output_start_sec": new_start, "output_end_sec": new_end}))
        cursor = new_end
    return packed


def find_first_death_sec(
    video_path: Path,
    start_sec: float,
    end_sec: float,
    *,
    sample_fps: float = 6.0,
    confirm_frames: int = 2,
    is_death: Callable[[object], bool] | None = None,
) -> float | None:
    """First confirmed death/spectator run in ``[start_sec, end_sec]``, or None.

    ``confirm_frames`` consecutive positive samples are required so a single
    noisy HUD frame does not split a live multi-kill.
    """
    lo, hi = float(start_sec), float(end_sec)
    if hi <= lo:
        return None
    need = max(1, int(confirm_frames))
    check = is_death or is_death_or_spectator_frame
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.warning("play_end: cannot open %s for death scan", video_path)
        return None
    try:
        step = 1.0 / max(1.0, float(sample_fps))
        t = lo
        streak = 0
        streak_start: float | None = None
        while t <= hi + 1e-9:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            hit = bool(ok and frame is not None and check(frame))
            if hit:
                if streak == 0:
                    streak_start = float(t)
                streak += 1
                if streak >= need:
                    return float(streak_start if streak_start is not None else t)
            else:
                streak = 0
                streak_start = None
            t += step
    finally:
        cap.release()
    return None


def collect_death_breaks(
    *,
    kill_times_by_video: dict[int, list[float]],
    video_paths: Sequence[Path],
    cfg: PlayEndConfig,
    finder: Callable[..., float | None] | None = None,
) -> list[tuple[int, float]]:
    """Death/spectator timestamps that must split kill groups (Layer 2)."""
    scan = finder or find_first_death_sec
    breaks: list[tuple[int, float]] = []
    confirm = int(getattr(cfg, "death_confirm_frames", 2) or 2)
    for video_index, times in kill_times_by_video.items():
        if not (0 <= int(video_index) < len(video_paths)):
            continue
        ordered = sorted(float(t) for t in times)
        path = video_paths[int(video_index)]
        for a, b in zip(ordered, ordered[1:]):
            if (b - a) < float(cfg.min_gap_for_break_sec):
                continue
            hit = scan(
                path,
                a + 0.05,
                b - 0.05,
                sample_fps=float(cfg.sample_fps),
                confirm_frames=confirm,
            )
            if hit is not None:
                breaks.append((int(video_index), float(hit)))
    breaks.sort(key=lambda x: (x[0], x[1]))
    return breaks


def _earliest_in_window(
    marks: Sequence[tuple[int, float]],
    video_index: int,
    lo: float,
    hi: float,
) -> float | None:
    hits = [float(t) for vi, t in marks if int(vi) == int(video_index) and lo < float(t) <= hi]
    return min(hits) if hits else None


def apply_play_end_to_clips(
    clips: Sequence[ScriptClip],
    *,
    cfg: PlayEndConfig,
    video_paths: Sequence[Path] | None = None,
    round_ends: Sequence[tuple[int, float]] | None = None,
    gemini_ends: dict[tuple[int, float], float] | None = None,
    death_finder: Callable[..., float | None] | None = None,
    death_marks: Sequence[tuple[int, float]] | None = None,
) -> list[ScriptClip]:
    """Layer 1 (+ optional L3 hints): clamp each clip, then repack the output bed."""
    if not cfg.enabled or not clips:
        return list(clips)
    round_map: dict[int, list[float]] = {}
    for vi, t in round_ends or ():
        round_map.setdefault(int(vi), []).append(float(t))
    gemini_map = gemini_ends or {}
    scan = death_finder or find_first_death_sec
    out: list[ScriptClip] = []
    for clip in clips:
        last_kill = float(clip.kill_timestamp_sec)
        recipe = str(clip.recipe or "clean")
        cap = recipe_max_post_sec(recipe, cfg)
        death_sec: float | None = None
        if video_paths is not None and 0 <= int(clip.video_index) < len(video_paths):
            death_sec = scan(
                video_paths[int(clip.video_index)],
                last_kill + _MIN_POST_SEC,
                last_kill + cap,
                sample_fps=float(cfg.sample_fps),
                confirm_frames=int(getattr(cfg, "death_confirm_frames", 2) or 2),
            )
        yolo_death = _earliest_in_window(
            death_marks or (),
            int(clip.video_index),
            last_kill + _MIN_POST_SEC,
            last_kill + cap,
        )
        if yolo_death is not None:
            death_sec = yolo_death if death_sec is None else min(death_sec, yolo_death)
        round_end = None
        for t in round_map.get(int(clip.video_index), []):
            if last_kill < t <= last_kill + cap:
                round_end = t if round_end is None else min(round_end, t)
        gemini_end = gemini_map.get((int(clip.video_index), round(last_kill, 3)))
        play_end = resolve_play_end_sec(
            last_kill_sec=last_kill,
            recipe=recipe,
            cfg=cfg,
            death_sec=death_sec,
            round_end_sec=round_end,
            video_end_sec=None,
            gemini_end_sec=gemini_end,
        )
        # Never extend past the already-planned source end.
        play_end = min(play_end, float(clip.end_sec))
        out.append(apply_source_and_output_end(clip, play_end_src=play_end, cfg=cfg))
    # Assembler concatenates by slot duration (ignores absolute gaps), so close the
    # bed. Kill accents slide with the clip — gameplay end wins over bar lock.
    return repack_output_timeline(out)
