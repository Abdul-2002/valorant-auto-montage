from src.pipeline.lyrics_align import _find_hooks, _snap_to_beats, hooks_from_structure
from src.pipeline.beat_analyzer import BeatMap, BeatSection


def test_should_match_hand_clap_ngrams() -> None:
    words = [
        (10.0, "just"),
        (10.2, "wanna"),
        (61.4, "hand"),
        (61.55, "clap"),
        (62.0, "hand"),
        (62.15, "clap"),
        (70.0, "put"),
        (70.1, "your"),
        (70.25, "hands"),
        (70.4, "up"),
    ]
    hooks = _find_hooks(words)
    assert (61.4, "HAND CLAP") in hooks
    assert any(line == "PUT YOUR HANDS UP" for _, line in hooks)


def test_should_snap_hooks_within_window() -> None:
    bm = BeatMap(
        tempo_bpm=140.0,
        beat_times=[61.0, 61.43, 61.86],
        onset_times=[],
        rms=[],
        sections=[BeatSection(61.0, 76.0, "chorus", 0.9)],
    )
    snapped = _snap_to_beats([(61.5, "HAND CLAP")], bm)
    assert abs(snapped[0][0] - 61.43) < 1e-6


def test_structure_fallback_still_works() -> None:
    bm = BeatMap(
        tempo_bpm=140.0,
        beat_times=[0.0, 1.0],
        onset_times=[],
        rms=[],
        sections=[BeatSection(10.0, 20.0, "chorus", 0.9)],
    )
    events = hooks_from_structure(bm, song_title="HandClap - Fitz and the Tantrums")
    assert events and events[0][0] == 10.0
