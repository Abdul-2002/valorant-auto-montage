"""Group close kills into one continuous montage clip (multi-kill sequences).

Separate fixed windows for kills 1-2s apart overlap in source time, so the
viewer sees the same footage twice. One clip per burst, with every kill on
its own beat, is how editors cut multi-kills.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from src.ai.enrichment import EnrichedEvent
from src.pipeline.beat_layout import GAP_BEATS_MIN, NOMINAL_SPEED, ClipDemand

# Same-spray window: kills inside this gap stay one burst before round-chaining.
MAX_KILL_GAP_SEC: float = 5.0
# Ace / extended multi — do not hard-cap at 5 and force a second clip mid-run.
MAX_KILLS_PER_CLIP: int = 10
# Same-VOD follow-up kills within this gap merge into one continuous play (2, 3, 4, n).
ROUND_GAP_SEC: float = 12.0
ROUND_SPAN_SEC: float = 45.0
ROUND_MIN_KILLS: int = 2
# Isolated kills at this score keep a 4–5s hold. Weaker ones are the kill only.
HOLD_SCORE: float = 0.73
# Shorter holds pack more bursts into the song bed; finale still gets grown bars.
HOLD_BARS: int = 2
PUNCH_BARS: int = 1
# Lead-in beats before the kill so the flick / crosshair placement is visible.
PUNCH_PRE_BEATS: int = 3
# Singles below this are filler even when the song bed still has room.
MIN_SINGLE_SCORE: float = 0.62
# Cap weak singles relative to multi-kills so the cut stays impact-dense.
_SINGLE_TO_MULTI_CAP: int = 3
_MIN_SINGLES_KEEP: int = 6
# Longer beds need denser packing (~one play per this many seconds of song).
_SEC_PER_SINGLE: float = 10.0
# Gemini (or detector) play labels → selection weight. Higher = more montage-worthy.
PLAY_LABEL_RANK: dict[str, int] = {
    "ace": 7,
    "clutch": 6,
    "multi": 5,  # multi-kill streak outranks a lone headshot for finale priority
    "headshot": 4,
    "op": 4,
    "clean": 2,
    "": 1,
    "junk": 0,
}
_KEEP_LABELS = frozenset({"ace", "clutch", "headshot", "op", "multi", "clean"})
# Dense curation: multi-kills + ace/clutch singles only (almost no filler singles).
_DENSE_SINGLE_LABELS = frozenset({"ace", "clutch"})


@dataclass(frozen=True)
class KillGroup:
    events: tuple[EnrichedEvent, ...]
    play_label: str = ""

    @property
    def video_index(self) -> int:
        return int(self.events[0].event.video_index)

    @property
    def kill_secs(self) -> tuple[float, ...]:
        return tuple(float(e.event.timestamp_sec) for e in self.events)

    @property
    def score(self) -> float:
        return max(float(e.event.score) for e in self.events)

    @property
    def scoped(self) -> bool:
        return any(bool(e.scoped) for e in self.events)

    @property
    def has_headshot(self) -> bool:
        if self.play_label == "headshot":
            return True
        return any(_is_headshot(e) for e in self.events)

    @property
    def source_fps(self) -> float:
        return float(self.events[0].source_fps)

    @property
    def video_duration_sec(self) -> float:
        return float(self.events[0].video_duration_sec)

    def demand(self) -> ClipDemand:
        secs = self.kill_secs
        gaps = tuple(b - a for a, b in zip(secs, secs[1:]))
        if len(self.events) != 1:
            return ClipDemand(src_kill_gaps=gaps, src_pre_available=secs[0])
        if self.score >= HOLD_SCORE:
            return ClipDemand(src_kill_gaps=gaps, src_pre_available=secs[0], fixed_bars=HOLD_BARS)
        return ClipDemand(
            src_kill_gaps=gaps,
            src_pre_available=secs[0],
            fixed_bars=PUNCH_BARS,
            pre_beats=PUNCH_PRE_BEATS,
        )


def _breaks_for_video(death_breaks: Sequence[tuple[int, float]] | None, video_index: int) -> tuple[float, ...]:
    if not death_breaks:
        return ()
    return tuple(float(t) for vi, t in death_breaks if int(vi) == int(video_index))


def _crosses_death_break(prev_kill_sec: float, next_kill_sec: float, breaks: Sequence[float]) -> bool:
    lo, hi = float(prev_kill_sec), float(next_kill_sec)
    return any(lo < float(b) <= hi for b in breaks)


def group_kills(
    events: Sequence[EnrichedEvent],
    *,
    max_gap_sec: float = MAX_KILL_GAP_SEC,
    max_kills: int = MAX_KILLS_PER_CLIP,
    death_breaks: Sequence[tuple[int, float]] | None = None,
) -> list[KillGroup]:
    """Split each video's kills into bursts; montage order follows source time.

    ``death_breaks`` are (video_index, time_sec) markers — a new burst starts when
    the gap from the previous kill crosses a player-death / spectator boundary.
    """
    by_video: dict[int, list[EnrichedEvent]] = {}
    for ev in events:
        by_video.setdefault(int(ev.event.video_index), []).append(ev)
    groups: list[KillGroup] = []
    for video_index, items in by_video.items():
        items.sort(key=lambda e: float(e.event.timestamp_sec))
        breaks = _breaks_for_video(death_breaks, video_index)
        current: list[EnrichedEvent] = []
        for ev in items:
            gap = float(ev.event.timestamp_sec) - float(current[-1].event.timestamp_sec) if current else 0.0
            died = bool(
                current
                and breaks
                and _crosses_death_break(float(current[-1].event.timestamp_sec), float(ev.event.timestamp_sec), breaks)
            )
            if current and (gap > max_gap_sec or len(current) >= max_kills or died):
                groups.append(KillGroup(tuple(current)))
                current = []
            current.append(ev)
        if current:
            groups.append(KillGroup(tuple(current)))
    groups.sort(key=lambda g: (g.kill_secs[0], g.video_index))
    return groups


def _best_label(groups: Sequence[KillGroup]) -> str:
    return max((g.play_label for g in groups), key=lambda lab: PLAY_LABEL_RANK.get(lab, 0), default="")


def _emit_chain(chain: Sequence[KillGroup]) -> list[KillGroup]:
    kills = sum(len(g.events) for g in chain)
    if len(chain) < 2 or kills < ROUND_MIN_KILLS:
        return list(chain)
    return [KillGroup(tuple(e for g in chain for e in g.events), play_label=_best_label(chain))]


def _chain_video(
    items: Sequence[KillGroup],
    *,
    death_breaks: Sequence[float] = (),
) -> list[KillGroup]:
    """Join consecutive groups while each step stays inside the round limits."""
    out: list[KillGroup] = []
    chain: list[KillGroup] = []
    for group in items:
        if chain:
            gap = group.kill_secs[0] - chain[-1].kill_secs[-1]
            span = group.kill_secs[-1] - chain[0].kill_secs[0]
            died = _crosses_death_break(chain[-1].kill_secs[-1], group.kill_secs[0], death_breaks)
            if gap > ROUND_GAP_SEC or span > ROUND_SPAN_SEC or died:
                out.extend(_emit_chain(chain))
                chain = []
        chain.append(group)
    if chain:
        out.extend(_emit_chain(chain))
    return out


def join_round_chains(
    groups: Sequence[KillGroup],
    *,
    death_breaks: Sequence[tuple[int, float]] | None = None,
) -> list[KillGroup]:
    """One clip for a same-VOD run of 2+ kills (double, triple, ace, …)."""
    by_video: dict[int, list[KillGroup]] = {}
    for group in groups:
        by_video.setdefault(group.video_index, []).append(group)
    merged: list[KillGroup] = []
    for video_index, items in by_video.items():
        items.sort(key=lambda g: g.kill_secs[0])
        merged.extend(_chain_video(items, death_breaks=_breaks_for_video(death_breaks, video_index)))
    merged.sort(key=lambda g: (g.kill_secs[0], g.video_index))
    return merged


def _is_headshot(ev: EnrichedEvent) -> bool:
    et = str(ev.event.event_type or "").lower().replace(" ", "_")
    return "headshot" in et or et in {"hs", "head_shot"}


def _quality_flag(group: KillGroup) -> int:
    """2 = headshot play, 1 = scoped, 0 = untagged."""
    if group.has_headshot:
        return 2
    if group.scoped or group.play_label == "op":
        return 1
    return 0


def _group_value(group: KillGroup) -> tuple[int, int, int, float]:
    """Impact key: label → kill count → HS/scoped → score.

    Kill count is second so a 3-kill ``multi`` still beats a 1-kill ``headshot``
    when ranks tie, and a labeled multi never loses finale to a lone HS.
    """
    return (
        PLAY_LABEL_RANK.get(str(group.play_label or ""), 1),
        len(group.events),
        _quality_flag(group),
        group.score,
    )


def with_locked_finale(groups: Sequence[KillGroup]) -> list[KillGroup]:
    """Form full multi-kill flows first, then park the biggest play as the ending.

    Chaining before locking is required: Valorant aces often sit 3–8s apart, so a
    tight spray window alone would lock a fragment and orphan the rest of the ace.
    Body rises by impact into the finale (not source-chronological filler).
    """
    chained = join_round_chains(groups)
    if len(chained) < 2:
        return chained
    finale = max(chained, key=_group_value)
    body = sorted(
        (g for g in chained if g is not finale),
        key=_group_value,
    )
    return body + [finale]


def _min_output_sec(group: KillGroup, beat_interval: float) -> float:
    internal = sum(group.demand().src_kill_gaps) / NOMINAL_SPEED
    return GAP_BEATS_MIN * beat_interval + internal


def fit_groups_to_duration(
    groups: Sequence[KillGroup],
    *,
    target_sec: float,
    beat_interval: float,
    min_clip_sec: Callable[[KillGroup], float] | None = None,
) -> list[KillGroup]:
    """Drop the weakest plays until the layout fits ``target_sec``.

    Singles go first; multi-kill flows stay intact (never trimmed to a last frag).
    """
    cost = min_clip_sec or (lambda g: _min_output_sec(g, beat_interval))
    kept = list(groups)
    while len(kept) > 1 and sum(cost(g) for g in kept) > target_sec:
        kept.remove(min(kept, key=_group_value))
    return kept


def curate_plays(
    groups: Sequence[KillGroup],
    *,
    target_sec: float,
    beat_interval: float,
    min_clip_sec: Callable[[KillGroup], float] | None = None,
    min_single_score: float = MIN_SINGLE_SCORE,
    density: str = "standard",
    clip_driven: bool = False,
) -> list[KillGroup]:
    """Keep multi-kills + strong/Gemini-labeled singles; drop junk even when the bed has room.

    ``density="dense"``: multis + ace/clutch singles only.
    ``clip_driven``: do not inflate the singles quota from a large song ceiling —
    bed length will follow the kept plays instead.
    """
    usable = [g for g in groups if g.play_label != "junk"]
    multis = [g for g in usable if len(g.events) >= 2]
    singles = [g for g in usable if len(g.events) == 1]
    if str(density) == "dense":
        bangers = [g for g in singles if g.play_label in _DENSE_SINGLE_LABELS]
        pool = list(multis) + bangers
        if not pool:
            pool = sorted(usable, key=_group_value, reverse=True)[:2] or list(groups)
    else:
        strong = [
            g
            for g in singles
            if g.play_label in _KEEP_LABELS or g.score >= float(min_single_score) or _quality_flag(g) > 0
        ]
        strong = sorted(strong, key=_group_value, reverse=True)
        if clip_driven:
            by_length = _MIN_SINGLES_KEEP
        else:
            by_length = max(_MIN_SINGLES_KEEP, int(float(target_sec) / _SEC_PER_SINGLE))
        cap = max(by_length, _SINGLE_TO_MULTI_CAP * max(1, len(multis)))
        strong = strong[:cap]
        pool = list(multis) + strong
        if not pool:
            pool = sorted(singles, key=_group_value, reverse=True)[:_MIN_SINGLES_KEEP] or list(usable) or list(groups)
    return fit_groups_to_duration(
        pool, target_sec=target_sec, beat_interval=beat_interval, min_clip_sec=min_clip_sec
    )


def move_finale_last(groups: Sequence[KillGroup]) -> list[KillGroup]:
    """The biggest burst closes the montage (editors save the best play for the end)."""
    if len(groups) < 2:
        return list(groups)
    finale = max(groups, key=_group_value)
    body = sorted(
        (g for g in groups if g is not finale),
        key=_group_value,
    )
    return body + [finale]


def collapse_killfeed_flicker(
    events: Sequence[EnrichedEvent], *, near_dup_sec: float = 0.8
) -> list[EnrichedEvent]:
    """Drop phantom re-emits in the same video; keep the higher-scored stamp.

    Does not strip real multi-kill members — those sit further apart than flicker.
    """
    by_video: dict[int, list[EnrichedEvent]] = {}
    for ev in events:
        by_video.setdefault(int(ev.event.video_index), []).append(ev)
    out: list[EnrichedEvent] = []
    for items in by_video.values():
        items = sorted(items, key=lambda e: float(e.event.timestamp_sec))
        kept: list[EnrichedEvent] = []
        for ev in items:
            if kept and abs(float(ev.event.timestamp_sec) - float(kept[-1].event.timestamp_sec)) <= near_dup_sec:
                if float(ev.event.score) > float(kept[-1].event.score):
                    kept[-1] = ev
                continue
            kept.append(ev)
        out.extend(kept)
    out.sort(key=lambda e: (int(e.event.video_index), float(e.event.timestamp_sec)))
    return out


def build_play_flows(
    events: Sequence[EnrichedEvent],
    *,
    near_dup_sec: float = 0.8,
    death_breaks: Sequence[tuple[int, float]] | None = None,
) -> list[KillGroup]:
    """Detector events → continuous plays (singles, sprays, full ace/quadra runs)."""
    clean = collapse_killfeed_flicker(events, near_dup_sec=near_dup_sec)
    return join_round_chains(group_kills(clean, death_breaks=death_breaks), death_breaks=death_breaks)
