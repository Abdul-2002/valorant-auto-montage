from src.ai.schema import MontageScript, ScriptClip
from src.config.models import OverlaysConfig
from src.effects.text_sprites import text_sprite, text_sprite_3d
from src.pipeline.montage_overlays import build_overlay_plan


def _clip(**kwargs) -> ScriptClip:
    base = dict(
        video_index=0,
        start_sec=0.0,
        end_sec=2.0,
        kill_timestamp_sec=1.0,
        score=0.8,
        output_start_sec=0.0,
        output_end_sec=3.0,
        kill_output_times_sec=[1.0],
        recipe="slow",
    )
    base.update(kwargs)
    return ScriptClip.model_validate(base)


def test_should_emit_burst_without_per_kill_spam() -> None:
    script = MontageScript(
        clips=[
            _clip(output_start_sec=0.0, kill_output_times_sec=[1.0]),
            _clip(
                output_start_sec=5.0,
                output_end_sec=10.0,
                kill_output_times_sec=[1.0, 2.0, 3.0],
                recipe="cinematic",
            ),
        ]
    )
    cfg = OverlaysConfig(title_text="", song_credit=False, per_kill_callouts=False, multi_kill_callouts=True)
    plan = build_overlay_plan(script=script, beat_map=None, cfg=cfg, song_title="", phase_sec=0.0)
    labels = [(round(e.at_sec, 2), e.text, e.kind) for e in plan.texts]
    assert (5.0 + 3.0, "TRIPLE KILL", "burst") in labels
    assert not any(e.kind == "kill" for e in plan.texts)


def test_should_place_lyric_hooks_when_enabled() -> None:
    script = MontageScript(clips=[_clip()])
    cfg = OverlaysConfig(title_text="", song_credit=False, lyrics_overlays=True, per_kill_callouts=False)
    plan = build_overlay_plan(
        script=script,
        beat_map=None,
        cfg=cfg,
        song_title="",
        phase_sec=0.0,
        lyric_events=[(12.5, "hand clap")],
    )
    assert any(e.kind == "lyric" and e.text == "HAND CLAP" and abs(e.at_sec - 12.5) < 1e-6 for e in plan.texts)


def test_should_plan_title_only_when_text_is_set() -> None:
    script = MontageScript(clips=[_clip()])
    cfg = OverlaysConfig(
        title_text="SHADOW",
        song_credit=False,
        per_kill_callouts=False,
        multi_kill_callouts=False,
        lyrics_overlays=False,
    )
    plan = build_overlay_plan(script=script, beat_map=None, cfg=cfg, song_title="song", phase_sec=0.0)
    assert [(e.text, e.kind) for e in plan.texts] == [("SHADOW", "title")]


def test_should_extrude_title_sprite_beyond_flat_sprite() -> None:
    flat = text_sprite("ACE", size=72, color=(255, 255, 255), glow=(80, 200, 255))
    deep = text_sprite_3d("ACE", size=72, color=(255, 255, 255), depth_color=(26, 66, 85), glow=(80, 200, 255))
    assert deep.shape[0] > flat.shape[0] and deep.shape[1] > flat.shape[1]
    assert (deep[:, :, 3] > 0).sum() > (flat[:, :, 3] > 0).sum()
