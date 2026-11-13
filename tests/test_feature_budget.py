import math

from src.ai.engine.feature_budget import GLITTER_FRACTION, MAX_GHOST_CANDIDATES, MAX_PIP, assign_features, glitter_slots


def test_should_glitter_the_finale_and_biggest_plays_but_not_neighbours() -> None:
    kill_counts = [1, 1, 3, 1, 2, 1, 1, 1, 1, 2]
    slots = glitter_slots(kill_counts=kill_counts, scores=[0.8] * len(kill_counts))
    assert 9 in slots
    assert 2 in slots
    assert len(slots) <= math.ceil(GLITTER_FRACTION * len(kill_counts))
    ordered = sorted(slots)
    assert all(b - a > 1 for a, b in zip(ordered, ordered[1:]))


def test_should_glitter_nothing_when_there_are_no_clips() -> None:
    assert glitter_slots(kill_counts=[], scores=[]) == set()


def test_should_put_pip_on_some_slow_singles_and_ghosts_on_others() -> None:
    n = 12
    recipes = ["slow"] * n
    recipes[0] = "clean"
    recipes[-1] = "cinematic"
    features = assign_features(recipes=recipes, kill_counts=[1] * n, scores=[0.4 + i * 0.04 for i in range(n)])
    pips = [i for i, f in enumerate(features) if f.pip_style]
    ghosts = [i for i, f in enumerate(features) if f.ghost_candidate]
    assert 1 <= len(pips) <= MAX_PIP
    assert set(features[i].pip_style for i in pips) <= {"freeze_inset", "replay_inset"}
    assert 0 not in pips and (n - 1) not in pips
    assert all(abs(a - b) > 1 for i, a in enumerate(pips) for b in pips[i + 1 :])
    assert 1 <= len(ghosts) <= MAX_GHOST_CANDIDATES
    assert not set(pips) & set(ghosts)


def test_should_skip_pip_on_multi_kill_clips() -> None:
    features = assign_features(recipes=["slow"] * 5, kill_counts=[3, 3, 3, 3, 3], scores=[0.9] * 5)
    assert all(not f.pip_style for f in features)


def test_should_hard_disable_pip_for_reference_style() -> None:
    n = 12
    recipes = ["slow"] * n
    features = assign_features(
        recipes=recipes,
        kill_counts=[1] * n,
        scores=[0.4 + i * 0.04 for i in range(n)],
        style_fx="reference",
    )
    assert all(not f.pip_style for f in features)
    assert any(f.gun_candidate for f in features)
