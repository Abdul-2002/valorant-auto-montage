from src.ai.engine.feature_budget import MAX_GHOST_CANDIDATES, MAX_PIP, assign_features


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
