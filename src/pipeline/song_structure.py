"""Song structure (beats, downbeats, labeled sections) via all-in-one-infer, cached as JSON.

torchaudio>=2.11 cannot decode mp3 without torchcodec, so the song is
converted to WAV with ffmpeg first; allin1 then reads it through soundfile.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from src.io.audio_loader import resolve_ffmpeg_exe

log = logging.getLogger(__name__)


class SongStructureError(RuntimeError):
    """Structure analysis could not run (missing dependency, decode or model failure)."""


@dataclass(frozen=True)
class SongSegment:
    start_sec: float
    end_sec: float
    label: str


@dataclass(frozen=True)
class SongStructure:
    bpm: float
    beats: list[float]
    downbeats: list[float]
    segments: list[SongSegment]

    @property
    def bar_sec(self) -> float:
        if len(self.downbeats) < 2:
            return 240.0 / max(1.0, self.bpm)
        return (self.downbeats[-1] - self.downbeats[0]) / (len(self.downbeats) - 1)


def _cache_key(audio_path: Path) -> str:
    stat = audio_path.stat()
    raw = f"{audio_path.resolve()}|{stat.st_size}|{int(stat.st_mtime)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _to_wav(audio_path: Path, work_dir: Path) -> Path:
    wav = work_dir / f"{audio_path.stem}.wav"
    if wav.exists():
        return wav
    cmd = [resolve_ffmpeg_exe(), "-y", "-i", str(audio_path), "-ar", "44100", "-ac", "2", str(wav)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise SongStructureError(f"ffmpeg could not convert {audio_path.name} to wav: {exc}") from exc
    return wav


def _run_allin1(wav: Path, work_dir: Path) -> SongStructure:
    try:
        import allin1_infer
    except ImportError as exc:
        raise SongStructureError("all-in-one-infer is not installed") from exc
    try:
        result = allin1_infer.analyze(
            str(wav),
            device="cuda",
            demix_dir=str(work_dir / "_demix"),
            spec_dir=str(work_dir / "_spec"),
            multiprocess=False,
        )
    except Exception as exc:
        raise SongStructureError(f"allin1 analysis failed for {wav.name}: {exc}") from exc
    return SongStructure(
        bpm=float(result.bpm),
        beats=[float(b) for b in result.beats],
        downbeats=[float(d) for d in result.downbeats],
        segments=[SongSegment(float(s.start), float(s.end), str(s.label)) for s in result.segments],
    )


def _load_cached(path: Path) -> SongStructure | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return SongStructure(
        bpm=float(data["bpm"]),
        beats=[float(b) for b in data["beats"]],
        downbeats=[float(d) for d in data["downbeats"]],
        segments=[SongSegment(**s) for s in data["segments"]],
    )


def analyze_song_structure(audio_path: Path, *, cache_dir: Path) -> SongStructure:
    """Beats, downbeats and labeled sections (intro/verse/chorus/bridge/outro/end)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"structure_{_cache_key(audio_path)}.json"
    cached = _load_cached(cache_file)
    if cached is not None:
        return cached
    structure = _run_allin1(_to_wav(audio_path, cache_dir), cache_dir)
    cache_file.write_text(json.dumps(asdict(structure), indent=2), encoding="utf-8")
    log.info(
        "song_structure: %s bpm=%.1f downbeats=%d sections=%s",
        audio_path.name,
        structure.bpm,
        len(structure.downbeats),
        [(round(s.start_sec, 1), s.label) for s in structure.segments],
    )
    return structure
