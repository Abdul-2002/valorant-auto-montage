"""Unit checks for Gemini kill-verify decision logic (no API calls)."""

from __future__ import annotations

from src.detection.gemini_kill_verify import _decision_accept, _parse_verify_json


def test_parse_verify_json_object() -> None:
    raw = '{"accept": true, "is_live_pov": true, "is_player_kill": true, "is_death_or_spectator": false, "confidence": 0.9, "reason": "skull"}'
    parsed = _parse_verify_json(raw)
    assert parsed is not None
    assert parsed["accept"] is True


def test_reject_death_cam() -> None:
    parsed = {
        "accept": True,
        "is_live_pov": False,
        "is_player_kill": False,
        "is_death_or_spectator": True,
        "confidence": 0.95,
        "reason": "death cam",
    }
    assert _decision_accept(parsed, 0.55) is False


def test_accept_live_kill() -> None:
    parsed = {
        "accept": True,
        "is_live_pov": True,
        "is_player_kill": True,
        "is_death_or_spectator": False,
        "confidence": 0.8,
        "reason": "pov kill",
    }
    assert _decision_accept(parsed, 0.55) is True


def test_reject_low_confidence() -> None:
    parsed = {
        "accept": True,
        "is_live_pov": True,
        "is_player_kill": True,
        "is_death_or_spectator": False,
        "confidence": 0.2,
        "reason": "unsure",
    }
    assert _decision_accept(parsed, 0.55) is False
