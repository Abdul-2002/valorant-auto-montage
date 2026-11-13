"""Final timeline locked to the song grid: cuts and kills on measured beats, ending on a section."""

from __future__ import annotations

from types import SimpleNamespace

from src.ai.engine.beat_grid_pack import (
    BeatSlot,
    GridAnchor,
    beat_slot,
    lock_to_beat_grid,
    pack_on_beat_grid,
    plan_grid_anchor,
)
from src.ai.schema import ScriptClip
from src.pipeline.time_remap import make_remap_fn

_BEAT = 0.75
_BEATS = [0.1 + i * _BEAT for i in range(120)]
_DOWNBEATS = _BEATS[::4]


def _section(start: float, end: float, kind: str) -> SimpleNamespace:
    return SimpleNamespace(start_sec=start, end_sec=end, section_type=kind)


def _clip(*, video: int, src_start: float, kill_out: list[float], kill_src: list[float], dur: float) -> ScriptClip:
    src_end = kill_src[-1] + 1.0
    knots = [(0.0, 0.0), *[(k, s - src_start) for k, s in zip(kill_out, kill_src)], (dur, src_end - src_start)]
    return ScriptClip(
        video_index=video,
        start_sec=src_start,
        end_sec=src_end,
        kill_timestamp_sec=kill_src[-1],
        kill_timestamps_sec=list(kill_src),
        score=0.8,
        output_start_sec=0.0,
        output_end_sec=dur,
        kill_output_times_sec=list(kill_out),
        time_knots=knots,
    )


def _trimmed_clips() -> list[ScriptClip]:
    """Tails cut to arbitrary lengths by the play-end layer (2.75 / 1.95 / 4.76 s)."""
    return [
        _clip(video=0, src_start=10.0, kill_out=[0.75], kill_src=[10.86], dur=2.75),
        _clip(video=1, src_start=20.0, kill_out=[1.5], kill_src=[21.7], dur=1.95),
        _clip(video=2, src_start=30.0, kill_out=[0.75, 2.26], kill_src=[30.86, 32.5], dur=4.76),
    ]


def _on_grid(t: float) -> bool:
    return min(abs(t - b) for b in _BEATS) < 1e-6


def test_should_round_kills_and_length_to_whole_beats_with_room_after_last_kill() -> None:
    slot = beat_slot(_trimmed_clips()[2], _BEAT)
    assert slot.kill_beats == (1, 3)
    assert slot.total_beats == 6
    short = _clip(video=0, src_start=0.0, kill_out=[0.75], kill_src=[0.86], dur=0.8)
    assert beat_slot(short, _BEAT) == BeatSlot(kill_beats=(1,), total_beats=2)


def test_should_put_every_cut_and_kill_on_a_measured_beat_when_packing() -> None:
    clips = _trimmed_clips()
    slots = [beat_slot(c, _BEAT) for c in clips]
    packed = pack_on_beat_grid(clips, slots, beats=_BEATS, interval=_BEAT, start_index=10)
    assert abs(float(packed[0].output_start_sec) - _BEATS[10]) < 1e-9
    for a, b in zip(packed, packed[1:]):
        assert abs(float(a.output_end_sec) - float(b.output_start_sec)) < 1e-9
    for clip in packed:
        assert _on_grid(float(clip.output_start_sec)) and _on_grid(float(clip.output_end_sec))
        for rel in clip.kill_output_times_sec:
            assert _on_grid(float(clip.output_start_sec) + rel)


def test_should_keep_the_exact_kill_frame_when_warping_knots() -> None:
    clips = _trimmed_clips()
    packed = pack_on_beat_grid(clips, [beat_slot(c, _BEAT) for c in clips], beats=_BEATS, interval=_BEAT, start_index=3)
    for clip in packed:
        fn = make_remap_fn(clip.time_knots, src_max=clip.end_sec - clip.start_sec)
        for rel_out, src_kill in zip(clip.kill_output_times_sec, clip.kill_timestamps_sec):
            assert abs(float(fn(rel_out)) - (src_kill - clip.start_sec)) < 1e-6
        assert abs(clip.time_knots[-1][0] - (float(clip.output_end_sec) - float(clip.output_start_sec))) < 1e-9


def test_should_end_block_on_first_high_energy_section_end_that_fits() -> None:
    slots = [BeatSlot((2,), 5), BeatSlot((2,), 5), BeatSlot((2,), 6)]
    sections = [_section(0.1, 30.1, "verse"), _section(30.1, 60.1, "verse"), _section(60.1, 78.1, "chorus")]
    anchor = plan_grid_anchor(slots=slots, beats=_BEATS, interval=_BEAT, downbeats=(), sections=sections)
    end_index = round((78.1 - 0.1) / _BEAT)
    assert anchor == GridAnchor(start_index=end_index - 16, finale_delta_beats=0)


def test_should_start_at_first_beat_when_no_high_energy_section_fits() -> None:
    slots = [BeatSlot((1,), 4)] * 3
    anchor = plan_grid_anchor(slots=slots, beats=_BEATS, interval=_BEAT, downbeats=(), sections=[_section(0.1, 5.0, "chorus")])
    assert anchor == GridAnchor(start_index=0, finale_delta_beats=0)


def test_should_land_a_cut_on_the_drop_by_trimming_the_finale_tail() -> None:
    slots = [BeatSlot((2,), 8)] * 4 + [BeatSlot((2,), 8)]
    drop = _BEATS[68]
    sections = [_section(0.1, drop, "verse"), _section(drop, _BEATS[104], "chorus")]
    anchor = plan_grid_anchor(slots=slots, beats=_BEATS, interval=_BEAT, downbeats=_DOWNBEATS, sections=sections)
    assert anchor == GridAnchor(start_index=68, finale_delta_beats=-4)


def test_should_snap_an_early_section_label_to_the_next_downbeat_drop() -> None:
    slots = [BeatSlot((2,), 8)] * 5
    labelled = _BEATS[67]
    sections = [_section(0.1, labelled, "verse"), _section(labelled, _BEATS[104], "chorus")]
    anchor = plan_grid_anchor(slots=slots, beats=_BEATS, interval=_BEAT, downbeats=_DOWNBEATS, sections=sections)
    assert anchor.start_index == 68


def test_should_lock_clips_so_the_montage_ends_on_the_chorus_end() -> None:
    clips = _trimmed_clips()
    sections = [_section(0.1, 47.35, "verse"), _section(47.35, 78.1, "chorus")]
    locked = lock_to_beat_grid(clips, beats=_BEATS, interval=_BEAT, downbeats=_DOWNBEATS, sections=sections)
    assert abs(float(locked[-1].output_end_sec) - 78.1) < 1e-6
    for clip in locked:
        for rel in clip.kill_output_times_sec:
            assert _on_grid(float(clip.output_start_sec) + rel)
