"""Kills shown on a death / spectator / round-end screen are not the player's play."""

from __future__ import annotations

from pathlib import Path

from src.ai.engine.play_end import kill_on_spectator_screen

_VIDEO = Path("fake.mp4")


def _finder(hit: float | None):
    def scan(_path, _lo, _hi, **_kwargs):
        return hit

    return scan


def test_should_flag_kill_when_spectator_run_starts_on_the_kill_frame() -> None:
    assert kill_on_spectator_screen(_VIDEO, 43.62, finder=_finder(43.57)) is True
    assert kill_on_spectator_screen(_VIDEO, 3.2, finder=_finder(3.275)) is True


def test_should_keep_kill_when_player_dies_after_it() -> None:
    assert kill_on_spectator_screen(_VIDEO, 10.0, finder=_finder(10.2)) is False


def test_should_keep_kill_when_no_spectator_frames() -> None:
    assert kill_on_spectator_screen(_VIDEO, 10.0, finder=_finder(None)) is False


def test_should_scan_a_short_window_around_the_kill() -> None:
    seen: dict[str, float] = {}

    def scan(_path, lo, hi, **kwargs):
        seen.update(lo=lo, hi=hi, confirm=kwargs["confirm_frames"])
        return None

    kill_on_spectator_screen(_VIDEO, 20.0, finder=scan)
    assert seen["lo"] < 20.0 < seen["hi"] <= 20.3
    assert seen["confirm"] >= 2
