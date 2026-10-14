"""Budget the signature per-kill features (PiP insets, ghost freeze-frames) across a montage.

Both are showpieces: on every kill they read as a template. PiP needs the
post-kill slow-mo to breathe, so it goes on single-kill slow clips; ghost
candidates are the strongest remaining kills (validated later by SAM).

Reference style (rafialihsan) does not use PiP cards — those are a different
look from the layered map/transition language in the Fiverr samples.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

PIP_STYLES: tuple[str, ...] = ("freeze_inset", "replay_inset")
MAX_PIP = 4
MAX_GHOST_CANDIDATES = 4
MAX_GUN_OUTLINES = 3
_GUN_RECIPES = frozenset({"slow", "cinematic"})


@dataclass(frozen=True)
class ClipFeatures:
    pip_style: str = ""
    ghost_candidate: bool = False
    gun_candidate: bool = False


def assign_features(
    *,
    recipes: Sequence[str],
    kill_counts: Sequence[int],
    scores: Sequence[float],
    style_fx: str = "",
) -> list[ClipFeatures]:
    """PiP styles alternate across non-adjacent slow single kills; ghosts go to the best of the rest."""
    n = len(recipes)
    last = n - 1
    # Hard-disable PiP for reference / rafialihsan — config.enabled=false is not enough
    # because effect_mapper re-enables per-clip when pip_style is set.
    pip_cap = 0 if style_fx == "reference" else MAX_PIP
    pip_pool = sorted(
        (i for i in range(1, last) if recipes[i] == "slow" and kill_counts[i] == 1),
        key=lambda i: scores[i],
        reverse=True,
    )
    pip_idx: list[int] = []
    for i in pip_pool:
        if len(pip_idx) >= pip_cap:
            break
        if all(abs(i - j) > 1 for j in pip_idx):
            pip_idx.append(i)
    pip_styles = {i: PIP_STYLES[k % len(PIP_STYLES)] for k, i in enumerate(sorted(pip_idx))}
    ghost_pool = sorted(
        (i for i in range(n) if i not in pip_styles),
        key=lambda i: (recipes[i] == "cinematic", scores[i]),
        reverse=True,
    )
    ghosts = set(ghost_pool[:MAX_GHOST_CANDIDATES])
    # Gun outline needs slow-mo screen time; it may stack with ghosts on showpiece kills.
    gun_pool = sorted(
        (i for i in range(1, n) if recipes[i] in _GUN_RECIPES and i not in pip_styles),
        key=lambda i: scores[i],
        reverse=True,
    )
    gun_idx: list[int] = []
    for i in gun_pool:
        if len(gun_idx) >= MAX_GUN_OUTLINES:
            break
        if all(abs(i - j) > 1 for j in gun_idx):
            gun_idx.append(i)
    guns = set(gun_idx)
    return [
        ClipFeatures(pip_style=pip_styles.get(i, ""), ghost_candidate=i in ghosts, gun_candidate=i in guns)
        for i in range(n)
    ]
