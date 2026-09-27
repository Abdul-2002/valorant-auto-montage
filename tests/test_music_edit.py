from src.pipeline.music_edit import SongPiece, _truncate_structure, remap_time
from src.pipeline.song_structure import SongSegment, SongStructure


def test_should_map_source_times_through_spliced_pieces() -> None:
    pieces = [SongPiece(0.0, 8.0, "intro"), SongPiece(40.0, 56.0, "chorus")]
    assert remap_time(2.0, pieces) == 2.0
    assert remap_time(20.0, pieces) is None
    assert abs(remap_time(40.0, pieces) - 8.0) < 1e-9
    assert abs(remap_time(56.0, pieces) - 24.0) < 1e-9


def test_should_truncate_structure_to_contiguous_window() -> None:
    structure = SongStructure(
        bpm=120.0,
        beats=[0.0, 0.5, 1.0, 1.5, 2.0, 2.5],
        downbeats=[0.0, 2.0],
        segments=[
            SongSegment(0.0, 2.0, "intro"),
            SongSegment(2.0, 4.0, "verse"),
        ],
    )
    truncated = _truncate_structure(structure, 2.0)
    assert truncated.beats == [0.0, 0.5, 1.0, 1.5, 2.0]
    assert truncated.downbeats == [0.0, 2.0]
    assert len(truncated.segments) == 1
    assert truncated.segments[0].label == "intro"
    assert abs(truncated.segments[0].end_sec - 2.0) < 1e-9
