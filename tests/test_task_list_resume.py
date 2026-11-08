from pathlib import Path

from src.app.routes.montage import _resume_path, _task_summary


def test_resume_path_prefers_edit_when_script_exists(tmp_path: Path) -> None:
    tdir = tmp_path / "job"
    tdir.mkdir()
    (tdir / "highlights.json").write_text("{}", encoding="utf-8")
    (tdir / "selection.json").write_text("{}", encoding="utf-8")
    (tdir / "montage_script.json").write_text("{}", encoding="utf-8")
    assert _resume_path(tdir) == "edit"


def test_task_summary_skips_non_jobs(tmp_path: Path) -> None:
    assert _task_summary("pending", tmp_path / "pending") is None
    job = tmp_path / "abc"
    job.mkdir()
    (job / "meta.json").write_text(
        '{"music":"/songs/music_Animal.mp3","videos":["a.mp4","b.mp4"]}',
        encoding="utf-8",
    )
    summary = _task_summary("abc", job)
    assert summary is not None
    assert summary.song_name == "Animal.mp3"
    assert summary.num_videos == 2
    assert summary.resume_path == "detect"
