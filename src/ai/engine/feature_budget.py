"""Budget the signature per-kill features (PiP insets, ghost freeze-frames) across a montage.

Both are showpieces: on every kill they read as a template. PiP needs the
post-kill slow-mo to breathe, so it goes on single-kill slow clips; ghost
candidates are the strongest remaining kills (validated later by SAM).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

PIP_STYLES: tuple[str, ...] = ("freeze_inset", "replay_inset")
MAX_PIP = 4
MAX_GHOST_CANDIDATES = 4


@dataclass(frozen=True)
class ClipFeatures:
    pip_style: str = ""
    ghost_candidate: bool = False


def assign_features(*, recipes: Sequence[str], kill_counts: Sequence[int], scores: Sequence[float]) -> list[ClipFeatures]:
    """PiP styles alternate across non-adjacent slow single kills; ghosts go to the best of the rest."""
    n = len(recipes)
    last = n - 1
    pip_pool = sorted(
        (i for i in range(1, last) if recipes[i] == "slow" and kill_counts[i] == 1),
        key=lambda i: scores[i],
        reverse=True,
    )
    pip_idx: list[int] = []
    for i in pip_pool:
        if len(pip_idx) >= MAX_PIP:
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
    return [ClipFeatures(pip_style=pip_styles.get(i, ""), ghost_candidate=i in ghosts) for i in range(n)]
