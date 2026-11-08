"""Montage flow scoring: per-play impact + sequence pacing/arc/variety.

Impact alone packs kills; flow scoring prefers sequences that rise into a finale,
mix multi-kills with strong singles, and avoid long runs of weak punches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.ai.engine.kill_grouping import PLAY_LABEL_RANK, KillGroup, _group_value, _quality_flag


@dataclass(frozen=True)
class PlayFlowScore:
    impact: float
    watchability: float
    combined: float


@dataclass(frozen=True)
class SequenceFlowScore:
    pacing: float
    arc: float
    variety: float
    combined: float


def score_play(group: KillGroup) -> PlayFlowScore:
    """0..1 impact and watchability for one play."""
    label_rank = PLAY_LABEL_RANK.get(str(group.play_label or ""), 1)
    impact = min(
        1.0,
        0.35 * (label_rank / 7.0)
        + 0.35 * min(1.0, len(group.events) / 5.0)
        + 0.20 * float(group.score)
        + 0.10 * (_quality_flag(group) / 2.0),
    )
    if group.play_label == "junk":
        impact = min(impact, 0.15)

    # Prefer kills with room before/after VOD edges (not clipped openers/closers).
    t0 = float(group.kill_secs[0])
    t1 = float(group.kill_secs[-1])
    dur = max(1.0, float(group.video_duration_sec))
    edge = min(t0, max(0.0, dur - t1))
    watchability = min(1.0, 0.45 + 0.55 * min(1.0, edge / 3.0))
    if len(group.events) >= 2:
        watchability = min(1.0, watchability + 0.1)
    combined = 0.7 * impact + 0.3 * watchability
    return PlayFlowScore(impact=impact, watchability=watchability, combined=combined)


def score_sequence(groups: Sequence[KillGroup]) -> SequenceFlowScore:
    """0..1 pacing / arc / variety for an ordered montage body+finale."""
    if not groups:
        return SequenceFlowScore(0.0, 0.0, 0.0, 0.0)
    plays = [score_play(g) for g in groups]
    n = len(groups)

    # Pacing: penalize long streaks of 1-kill punches; reward multi presence.
    streak = 0
    max_streak = 0
    multi_n = 0
    for g in groups:
        if len(g.events) >= 2:
            multi_n += 1
            streak = 0
        else:
            streak += 1
            max_streak = max(max_streak, streak)
    pacing = 1.0 - min(0.7, 0.12 * max(0, max_streak - 2))
    pacing = min(1.0, pacing + 0.15 * min(1.0, multi_n / max(1, n // 2)))

    # Arc: finale should be among the top impact plays; body should generally rise.
    impacts = [p.impact for p in plays]
    finale = impacts[-1]
    body = impacts[:-1] if n > 1 else []
    arc = 0.55 + 0.45 * (1.0 if finale >= max(impacts) - 1e-6 else 0.35)
    if len(body) >= 2:
        rises = sum(1 for a, b in zip(body, body[1:]) if b + 1e-6 >= a)
        arc = 0.5 * arc + 0.5 * (rises / (len(body) - 1))

    # Variety: distinct videos and labels.
    videos = {g.video_index for g in groups}
    labels = {str(g.play_label or "") for g in groups}
    variety = 0.5 * min(1.0, len(videos) / min(4, n)) + 0.5 * min(1.0, len(labels) / min(4, n))

    combined = 0.4 * pacing + 0.35 * arc + 0.25 * variety
    return SequenceFlowScore(pacing=pacing, arc=arc, variety=variety, combined=combined)


def rank_for_flow(groups: Sequence[KillGroup]) -> list[KillGroup]:
    """Sort plays by flow impact (desc) for recommendation lists."""
    return sorted(groups, key=lambda g: (score_play(g).combined, _group_value(g)), reverse=True)


def resolve_recommend_budget(
    n_plays: int,
    *,
    max_plays: int = 0,
    min_plays: int | None = None,
    density: str = "standard",
) -> tuple[int, int]:
    """Resolve play budget from config.

    ``max_plays <= 0`` means all YOLO-derived plays (no artificial ceiling).
    When the ceiling is unlimited, the floor matches so flow scoring does not trim.
    """
    n = max(0, int(n_plays))
    if int(max_plays) <= 0:
        return n, n
    mx = min(int(max_plays), n)
    if min_plays is None:
        floor = 10 if str(density) == "dense" else 6
    else:
        floor = int(min_plays)
    mn = min(max(floor, 0), mx)
    return mx, mn


def pick_recommended(
    groups: Sequence[KillGroup],
    *,
    max_plays: int = 0,
    min_plays: int | None = None,
    density: str = "standard",
) -> list[KillGroup]:
    """Greedy pick that fills a play budget without collapsing on a single perfect play.

    A lone play scores sequence_flow≈1.0; requiring `seq >= best` forever freezes at
    1 clip. Fill to ``min_plays`` first, then only accept additions that do not tank
    flow by more than a small slack.

    ``max_plays <= 0`` selects every usable YOLO-derived play (testing / no ceiling).
    """
    usable = [g for g in groups if g.play_label != "junk"]
    if str(density) == "dense":
        usable = [g for g in usable if len(g.events) >= 2 or g.play_label in {"ace", "clutch"}]
    if not usable:
        usable = list(groups)
    ranked = rank_for_flow(usable)
    max_cap, min_cap = resolve_recommend_budget(
        len(ranked),
        max_plays=max_plays,
        min_plays=min_plays,
        density=density,
    )
    if max_cap <= 0:
        return []
    picked: list[KillGroup] = []
    best_seq = -1.0
    for cand in ranked:
        if len(picked) >= max_cap:
            break
        trial = picked + [cand]
        # Keep a provisional finale = best impact in trial.
        finale = max(trial, key=lambda g: (score_play(g).combined, _group_value(g)))
        body = [g for g in trial if g is not finale]
        body.sort(key=lambda g: score_play(g).combined)
        ordered = body + [finale]
        seq = score_sequence(ordered).combined
        filling = len(picked) < min_cap
        if not picked or filling or seq >= best_seq - 0.08:
            picked = list(trial)
            if seq >= best_seq:
                best_seq = seq
            elif filling and best_seq < 0:
                best_seq = seq
    finale = max(picked, key=lambda g: (score_play(g).combined, _group_value(g))) if picked else None
    if finale is None:
        return []
    body = sorted((g for g in picked if g is not finale), key=lambda g: score_play(g).combined)
    return body + [finale]
