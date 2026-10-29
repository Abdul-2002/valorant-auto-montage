"""Canonical YouTube listing: song title, credits, shots, hashtags."""

from __future__ import annotations

from src.youtube.listing import (
    build_upload_listing,
    chapter_labels,
    chapter_times,
    is_placeholder_description,
    is_placeholder_title,
    merge_upload_listing,
    shot_times_from_script,
    song_hashtag_slug,
)


def test_should_use_song_name_only_as_title() -> None:
    listing = build_upload_listing(song_title="Die For You")
    assert listing["title"] == "Die For You"
    assert "montage" not in str(listing["title"]).lower()


def test_should_add_credits_hashtags_and_shots() -> None:
    listing = build_upload_listing(
        song_title="Die For You",
        song_credit="Song: Die For You ft. Grabbitz (VALORANT Champions 2021).",
        shot_times_sec=[0.64, 5.07, 10.1, 20.2, 32.0, 45.0],
    )
    description = str(listing["description"])
    assert description.startswith("Song: Die For You ft. Grabbitz")
    assert "Private test upload" not in description
    assert "#valorantmontage" in description
    assert "#dieforyou" in description
    assert "Shots:" in description
    assert "0:05 Shot 2" in description
    assert "Chapters:" in description
    assert listing["privacy_status"] == "public"
    assert "dieforyou" in listing["tags"]


def test_should_drop_final_chapter_when_shorter_than_ten_seconds() -> None:
    marks = chapter_times([2.0, 11.0, 22.0, 33.0, 44.0, 55.0], duration_sec=56.9)
    assert marks == [0.0, 11.0, 22.0, 33.0, 44.0]
    labels = chapter_labels(len(marks))
    assert len(set(labels)) == len(labels)
    assert labels[0] == "Intro" and labels[-1] == "Final"


def test_should_list_chapters_before_shots_when_both_present() -> None:
    listing = build_upload_listing(song_title="Fire Again", shot_times_sec=[0.4, 11.0, 22.0, 33.0], duration_sec=45.0)
    description = str(listing["description"])
    assert description.index("Chapters:") < description.index("Shots:")


def test_should_slug_song_hashtag() -> None:
    assert song_hashtag_slug("Die For You") == "dieforyou"


def test_should_map_script_kills_onto_montage_timeline() -> None:
    script = {
        "clips": [
            {
                "output_start_sec": 72.0,
                "output_end_sec": 76.0,
                "kill_output_times_sec": [0.64],
            },
            {
                "output_start_sec": 76.0,
                "output_end_sec": 80.0,
                "kill_output_times_sec": [1.27],
            },
        ]
    }
    times = shot_times_from_script(script)
    assert times[0] == 0.64
    assert abs(times[1] - 5.27) < 0.01


def test_should_offset_late_in_clip_kills_by_clip_start() -> None:
    script = {
        "clips": [
            {"output_start_sec": 72.0, "output_end_sec": 76.0, "kill_output_times_sec": [0.5]},
            {"output_start_sec": 76.0, "output_end_sec": 84.0, "kill_output_times_sec": [6.0]},
        ]
    }
    assert abs(shot_times_from_script(script)[1] - 10.0) < 0.01


def test_should_replace_placeholder_client_metadata() -> None:
    merged = merge_upload_listing(
        song_title="Die For You",
        shot_times_sec=[0.0, 12.0],
        title="Valorant montage run 31 — Die For You",
        description="Private test upload of run 31.\nSong: x",
        tags=[],
        privacy_status="public",
    )
    assert merged["title"] == "Die For You"
    assert "Private test upload" not in str(merged["description"])
    assert "#valorantmontage" in str(merged["description"])


def test_should_detect_placeholder_title_and_description() -> None:
    assert is_placeholder_title("Valorant montage run 31 — Die For You")
    assert is_placeholder_description("Private test upload of run 31.")
    assert not is_placeholder_title("Die For You")
