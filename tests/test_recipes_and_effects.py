"""Recipes (every kill hit, budgets, scope gating) and kill-hit / edge-glow frame ops."""

from __future__ import annotations

import numpy as np

from src.ai.engine.effect_mapper import (
    MAX_CINEMATIC,
    EffectMappingInput,
    assign_hit_styles,
    assign_recipes,
    map_effects,
)
from src.effects.edge_glow import edge_map, tritone
from src.effects.envelopes import decay_envelope
from src.effects.kill_hit import KillHitEffect


def _effects(recipe: str, scoped: bool = False):
    return map_effects(
        inp=EffectMappingInput(score=0.9, arc_phase="climax"),
        creative_config={},
        brief=None,
        recipe=recipe,
        scoped=scoped,
    )


def test_should_hit_every_kill_when_any_recipe_is_used() -> None:
    for recipe in ("clean", "punch", "slow", "cinematic"):
        eff = _effects(recipe)
        assert eff.kill_hit is not None and eff.kill_hit.enabled


def test_should_slow_after_kill_only_for_slow_and_cinematic() -> None:
    assert _effects("clean").velocity.kill_slowmo_duration_sec == 0.0
    assert _effects("punch").velocity.kill_slowmo_duration_sec == 0.0
    assert _effects("slow").velocity.kill_slowmo_duration_sec > 0.0
    assert _effects("cinematic").velocity.kill_slowmo_duration_sec > 0.0


def test_should_add_scope_mask_only_when_kill_was_scoped() -> None:
    assert _effects("slow").scope_vignette is None
    assert _effects("slow", scoped=True).scope_vignette is not None


def test_should_reserve_edge_glow_for_cinematic() -> None:
    assert _effects("cinematic").edge_glow is not None
    assert _effects("punch").edge_glow is None


def test_should_move_the_camera_on_every_recipe() -> None:
    for recipe in ("clean", "punch", "slow", "cinematic"):
        cam = _effects(recipe).camera
        assert cam is not None and cam.enabled
    assert _effects("punch").camera.crash_zoom > 0.0
    assert _effects("slow").camera.push_in > 0.0
    assert _effects("clean").zoom is None
    assert _effects("punch").shake is None


def test_should_enable_pip_only_when_a_style_is_budgeted() -> None:
    bare = _effects("slow")
    assert bare.pip_inset is None
    pip = map_effects(
        inp=EffectMappingInput(score=0.9, arc_phase="build"),
        creative_config={},
        brief=None,
        recipe="slow",
        pip_style="freeze_inset",
    )
    assert pip.pip_inset is not None and pip.pip_inset.enabled
    assert pip.pip_inset.style == "freeze_inset"


def test_should_cap_cinematic_and_default_to_slow_when_undirected() -> None:
    n = 16
    recipes = assign_recipes(scores=[0.5 + i / 40 for i in range(n)], phases=["climax"] * n)
    assert recipes.count("cinematic") <= MAX_CINEMATIC
    assert recipes.count("slow") >= max(recipes.count(r) for r in ("clean", "punch"))


def test_should_honor_director_recipe_over_rotation() -> None:
    recipes = assign_recipes(scores=[0.5] * 4, phases=["build"] * 4, directed={2: "clean"})
    assert recipes[2] == "clean"


def test_should_vary_hit_styles_and_honor_director_choice() -> None:
    styles = assign_hit_styles(n=8, directed={0: "glow"})
    assert styles[0] == "glow"
    assert len(set(styles)) >= 2


def test_should_peak_hit_on_kill_frame_and_be_silent_before_it() -> None:
    assert decay_envelope(0.99, 1.0, 0.3) == 0.0
    assert decay_envelope(1.0, 1.0, 0.3) == 1.0
    assert decay_envelope(1.31, 1.0, 0.3) == 0.0


def test_should_hit_later_kills_of_a_burst_harder() -> None:
    hit = KillHitEffect(minor_scale=0.6)
    anchors = (1.0, 2.0)
    assert abs(hit._strength(1.0, anchors) - 0.6) < 1e-9
    assert abs(hit._strength(2.0, anchors) - 1.0) < 1e-9


def test_should_brighten_frame_when_flash_blur_hit_fires() -> None:
    frame = np.full((108, 192, 3), 60, dtype=np.uint8)
    out = KillHitEffect(style="flash_blur", flash_strength=0.5)._hit(frame, 1.0)
    assert out.mean() > frame.mean() + 40


def test_should_render_edges_in_a_single_hue() -> None:
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    frame[:, 80:] = 255
    lines = tritone(edge_map(frame), np.array([40.0, 140.0, 255.0]), np.array([210.0, 240.0, 255.0]))
    edge_px = lines[lines.sum(axis=2) > 0.3]
    assert edge_px.size > 0
    assert np.all(edge_px[:, 2] >= edge_px[:, 0])
    assert lines[:, :60].max() == 0.0
