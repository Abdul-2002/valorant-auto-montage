import numpy as np
import pytest
from moviepy import ColorClip

from src.ai.engine.effect_mapper import EffectMappingInput, assign_glitter_variants, map_effects
from src.effects.base import EffectContext
from src.effects.glitter import GLITTER_VARIANTS, GlitterEffect

W, H = 320, 180


def _render(effect: GlitterEffect, t: float, kills: tuple[float, ...] = (0.5,)) -> np.ndarray:
    clip = ColorClip(size=(W, H), color=(30, 30, 30), duration=2.0)
    ctx = EffectContext(
        clip=clip, kill_timestamp=None, beat_timestamp=None, clip_duration=2.0, fps=30,
        resolution=(W, H), config={}, kill_timestamps=kills,
    )
    return effect.apply(ctx).get_frame(t)


def test_should_mix_repeats_and_changes_when_rotating_variants() -> None:
    variants = assign_glitter_variants(10)
    assert set(variants) == set(GLITTER_VARIANTS)
    assert any(a == b for a, b in zip(variants, variants[2:]))
    assert all(a != b for a, b in zip(variants, variants[1:]))


@pytest.mark.parametrize("variant", GLITTER_VARIANTS)
def test_should_add_bright_sparkles_when_inside_kill_window(variant: str) -> None:
    frame = _render(GlitterEffect(variant=variant, seed=7), 0.62)
    assert frame.max() > 120 and (frame > 60).mean() > 0.002


def test_should_leave_frame_untouched_when_outside_kill_window() -> None:
    before, after = _render(GlitterEffect(seed=7), 0.4), _render(GlitterEffect(seed=7), 1.5)
    assert before.max() == 30 and after.max() == 30


def test_should_render_identically_when_seed_matches() -> None:
    a = _render(GlitterEffect(seed=3), 0.7)
    assert np.array_equal(a, _render(GlitterEffect(seed=3), 0.7))
    assert not np.array_equal(a, _render(GlitterEffect(seed=4), 0.7))


def test_should_attach_glitter_when_mapper_gets_variant() -> None:
    effects = map_effects(
        inp=EffectMappingInput(score=0.8, arc_phase="build"), creative_config={}, brief=None,
        glitter_variant="streak", glitter_seed=11,
    )
    assert effects.glitter is not None and effects.glitter.variant == "streak" and effects.glitter.seed == 11
    assert map_effects(inp=EffectMappingInput(score=0.8, arc_phase="build"), creative_config={}, brief=None).glitter is None
