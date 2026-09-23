"""Beat-drop hold must tick the pre-kill frame without moving the kill off the accent."""

from __future__ import annotations

import numpy as np

from src.ai.engine.effect_mapper import EffectMappingInput, map_effects
from src.effects.velocity import aligned_source_times


def test_kill_frame_stays_on_accent_when_drop_hold_is_on() -> None:
    pre_out, slow_out, pre_src, slow_src, fac = 2.0, 0.6, 1.4, 0.21, 0.35
    kill_t = pre_out + slow_out / 2.0
    src = aligned_source_times(
        np.array([kill_t]),
        pre_out=pre_out,
        slow_out=slow_out,
        pre_src=pre_src,
        slow_src=slow_src,
        slowmo_fac=fac,
        post_v=1.2,
        src_eps=3.0,
        drop_hold=True,
        fps=60,
    )
    assert abs(float(src[0]) - (pre_src + slow_src / 2.0)) < 1e-6


def test_drop_hold_repeats_the_pre_kill_frame() -> None:
    pre_out, pre_src = 2.0, 1.4
    held = aligned_source_times(
        np.linspace(pre_out - 0.42, pre_out - 0.01, 8),
        pre_out=pre_out,
        slow_out=0.6,
        pre_src=pre_src,
        slow_src=0.21,
        slowmo_fac=0.35,
        post_v=1.2,
        src_eps=3.0,
        drop_hold=True,
        fps=60,
    )
    assert np.all(np.abs(held - pre_src) <= (1.0 / 60.0) + 1e-6)
    assert len(set(np.round(held, 5))) >= 2


def test_cinematic_recipe_has_no_corner_replay_or_lens_warp() -> None:
    effects = map_effects(
        inp=EffectMappingInput(score=1.0, arc_phase="climax"),
        creative_config={},
        brief=None,
        recipe="cinematic",
    )
    assert effects.death_pip is None
    assert effects.lens_distort is None
    assert effects.highlight_bloom is not None
