from src.ai.schema import MontageScript, ScriptClip, ScriptTransition
from src.pipeline.ffmpeg_assemble import can_use_ffmpeg_assemble


def test_should_allow_ffmpeg_when_only_hard_cuts_and_no_pixel_fx() -> None:
    script = MontageScript(
        clips=[
            ScriptClip(
                video_index=0,
                start_sec=1.0,
                end_sec=2.0,
                kill_timestamp_sec=1.5,
                score=0.8,
                output_start_sec=0.0,
                output_end_sec=1.0,
                transition_to_next=ScriptTransition(type="hard_cut", duration_sec=0.1),
            ),
            ScriptClip(
                video_index=0,
                start_sec=3.0,
                end_sec=4.0,
                kill_timestamp_sec=3.5,
                score=0.8,
                output_start_sec=1.0,
                output_end_sec=2.0,
            ),
        ]
    )
    assert can_use_ffmpeg_assemble(script) is True


def test_should_reject_ffmpeg_when_jigsaw_or_remap_present() -> None:
    script = MontageScript(
        clips=[
            ScriptClip(
                video_index=0,
                start_sec=1.0,
                end_sec=2.0,
                kill_timestamp_sec=1.5,
                score=0.8,
                output_start_sec=0.0,
                output_end_sec=1.0,
                time_knots=[(0.0, 0.0), (0.5, 0.4), (1.0, 0.9)],
                transition_to_next=ScriptTransition(type="jigsaw", duration_sec=0.5),
            )
        ]
    )
    assert can_use_ffmpeg_assemble(script) is False
