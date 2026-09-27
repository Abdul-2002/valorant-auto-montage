"""End-to-end script planning: every kill on a beat, exact kill frame, no repeated footage."""

from __future__ import annotations

from src.ai.engine.composer import ComposeInputs, compose_script
from src.ai.enrichment import EnrichedEvent
from src.pipeline.beat_analyzer import BeatMap, BeatSection
from src.pipeline.time_remap import make_remap_fn
from src.pipeline.types import DetectedEvent

_INTERVAL = 0.44


def _beat_map(n: int = 420) -> BeatMap:
    beats = [2.0 + i * _INTERVAL for i in range(n)]
    return BeatMap(
        tempo_bpm=136.0,
        beat_times=beats,
        onset_times=[],
        rms=[],
        sections=[BeatSection(start_sec=20.0, end_sec=beats[-1], section_type="chorus", avg_energy=0.8)],
        beat_strengths=[0.9 if i % 2 else 0.3 for i in range(n)],
    )


def _events() -> list[EnrichedEvent]:
    kills = [(0, t) for t in (12.0, 13.1, 14.3, 40.0, 75.0, 76.4, 120.0, 180.0, 181.2)]
    kills += [(1, t) for t in (8.0, 30.0, 31.0, 55.0, 90.0)]
    return [
        EnrichedEvent(
            event=DetectedEvent(video_index=v, timestamp_sec=t, score=0.8, event_type="kill"),
            video_duration_sec=300.0,
            gap_prev_sec=None,
            gap_next_sec=None,
            multi_kill_group_id=None,
            source_fps=120.0 if v == 1 else 60.0,
        )
        for v, t in kills
    ]


def _script():
    return compose_script(
        ComposeInputs(
            enriched_events=_events(),
            beat_map=_beat_map(),
            creative_config_resolved={"effect_intensity": 0.8},
            brief=None,
            target_duration_sec=60,
        )
    )


def test_should_place_every_kill_on_a_beat() -> None:
    beats = _beat_map().beat_times
    for clip in _script().clips:
        for rel in clip.kill_output_times_sec:
            t = float(clip.output_start_sec) + rel
            assert min(abs(t - b) for b in beats) < 1e-6


def test_should_show_the_exact_kill_frame_at_its_beat() -> None:
    for clip in _script().clips:
        fn = make_remap_fn(clip.time_knots, src_max=clip.end_sec - clip.start_sec)
        for rel_out, src_kill in zip(clip.kill_output_times_sec, clip.kill_timestamps_sec):
            assert abs(float(fn(rel_out)) - (src_kill - clip.start_sec)) < 1e-6


def test_should_cut_multi_kills_as_one_clip() -> None:
    counts = sorted(len(c.kill_timestamps_sec) for c in _script().clips)
    assert counts[-1] == 3
    assert sum(counts) == len(_events())


def test_should_not_repeat_source_footage_between_clips() -> None:
    clips = _script().clips
    for i, a in enumerate(clips):
        for b in clips[i + 1 :]:
            if a.video_index != b.video_index:
                continue
            assert min(a.end_sec, b.end_sec) - max(a.start_sec, b.start_sec) <= 0.0


def test_should_hit_every_clip_and_cap_60fps_slowmo_at_half_speed() -> None:
    for clip in _script().clips:
        assert clip.effects.kill_hit is not None
        vel = clip.effects.velocity
        if clip.video_index == 0 and vel.kill_slowmo_duration_sec > 0:
            assert vel.kill_slowmo_factor >= 0.5
