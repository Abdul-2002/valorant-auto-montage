"""Editorial pacing guards for a tighter, more professional montage feel."""

from __future__ import annotations

from src.ai.schema import ScriptClip, ScriptTransition

# ~2 beats at typical montage tempos (120–150 BPM) — enough setup, not dead air.
MAX_PRE_ROLL_SEC: float = 1.5
# Fancy transitions need air after the last kill or they read as mistimed.
MIN_SETTLE_BEFORE_TRANSITION_SEC: float = 1.2
_FANCY_TRANSITIONS = frozenset({"jigsaw", "whip_pan", "spin", "flash_white"})


def _pre_roll_budget(*, max_pre_sec: float, beat_sec: float | None) -> float:
    """Whole-beat pre-roll when a beat grid exists; otherwise the hard time budget."""
    max_pre = float(max_pre_sec)
    if beat_sec is None or float(beat_sec) <= 1e-9:
        return max_pre
    beat = float(beat_sec)
    # Prefer as many whole beats as fit under the budget; always keep at least one beat
    # of setup even when a single beat is slightly longer than max_pre.
    n_beats = max(1, int(max_pre / beat))
    return n_beats * beat


def cap_pre_roll(
    *,
    kill_out_rel: list[float],
    out_duration: float,
    max_pre_sec: float = MAX_PRE_ROLL_SEC,
    beat_sec: float | None = None,
) -> tuple[list[float], float]:
    """Shift the slot so the first kill lands within the pre-roll budget.

    When ``beat_sec`` is set, the budget is snapped to whole beats so the cut-in
    and the kill stay on the grid. Returns updated relative kill times and the
    shortened output duration.
    """
    if not kill_out_rel:
        return list(kill_out_rel), float(out_duration)
    first = float(kill_out_rel[0])
    max_pre = _pre_roll_budget(max_pre_sec=max_pre_sec, beat_sec=beat_sec)
    if first <= max_pre + 1e-9:
        return [float(k) for k in kill_out_rel], float(out_duration)
    delta = first - max_pre
    shifted = [float(k) - delta for k in kill_out_rel]
    # Keep enough post-kill air for settle/slow-mo; do not collapse the clip onto the kill.
    min_tail = max(0.75, float(MIN_SETTLE_BEFORE_TRANSITION_SEC) * 0.75)
    new_dur = max(shifted[-1] + min_tail, float(out_duration) - delta)
    return shifted, new_dur


def enforce_transition_settle(
    clips: list[ScriptClip],
    *,
    min_settle_sec: float = MIN_SETTLE_BEFORE_TRANSITION_SEC,
) -> list[ScriptClip]:
    """Downgrade jigsaw/whip/etc. to a hard cut when post-kill settle is too short."""
    if not clips:
        return []
    out: list[ScriptClip] = []
    for clip in clips:
        tr = clip.transition_to_next
        if tr is None or str(tr.type) not in _FANCY_TRANSITIONS:
            out.append(clip)
            continue
        kills = list(clip.kill_output_times_sec or [])
        last_kill = float(kills[-1]) if kills else 0.0
        out_start = float(clip.output_start_sec or 0.0)
        out_end = float(clip.output_end_sec or 0.0)
        settle = (out_end - out_start) - last_kill
        if settle + 1e-9 >= float(min_settle_sec):
            out.append(clip)
            continue
        out.append(
            clip.model_copy(
                update={
                    "transition_to_next": ScriptTransition(type="hard_cut", duration_sec=0.12),
                }
            )
        )
    return out
