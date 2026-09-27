"""Splice a song at downbeats so the montage runs intro -> strongest sections -> the song's real ending.

Pieces are whole bars, so the bar grid stays continuous across every splice.
Each join is a short crossfade centered on the downbeat that does not change
the edited length (beat times remap exactly).
"""

from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass
from pathlib import Path

from src.io.audio_loader import load_audio_segment
from src.pipeline.song_structure import SongSegment, SongStructure

log = logging.getLogger(__name__)

HIGH_ENERGY_LABELS = frozenset({"chorus", "inst", "solo", "drop"})
ENDING_LABELS = frozenset({"end", "outro"})
_BODY_PRIORITY = {"chorus": 0, "drop": 0, "inst": 1, "solo": 1, "bridge": 2, "verse": 3, "break": 4}
INTRO_MAX_BARS = 8
MIN_PIECE_BARS = 4
# 30ms reads as a hard cut across section jumps; 300ms softens intro→chorus teleports.
SPLICE_XFADE_MS = 300


@dataclass(frozen=True)
class SongPiece:
    src_start: float
    src_end: float
    label: str

    @property
    def duration(self) -> float:
        return self.src_end - self.src_start


def _snap(t: float, downbeats: list[float]) -> float:
    i = bisect.bisect_left(downbeats, t)
    candidates = [downbeats[j] for j in (i - 1, i) if 0 <= j < len(downbeats)]
    return min(candidates, key=lambda d: abs(d - t)) if candidates else t


def _finale_block(segments: list[SongSegment]) -> tuple[int, int]:
    """Index range [a, b] of the last run of consecutive high-energy sections."""
    b = max((i for i, s in enumerate(segments) if s.label in HIGH_ENERGY_LABELS), default=len(segments) - 1)
    a = b
    while a - 1 >= 0 and segments[a - 1].label in HIGH_ENERGY_LABELS:
        a -= 1
    return a, b


def _body_pieces(
    segments: list[SongSegment], downbeats: list[float], lo: float, hi: float, budget: float, bar: float
) -> list[SongPiece]:
    """Whole sections between intro and finale by priority, then one partial section to fill."""
    cands = [s for s in segments if s.start_sec >= lo - 1e-3 and s.end_sec <= hi + 1e-3]
    cands.sort(key=lambda s: (_BODY_PRIORITY.get(s.label, 5), s.start_sec))
    picked: list[SongPiece] = []
    for s in cands:
        piece = SongPiece(_snap(s.start_sec, downbeats), _snap(s.end_sec, downbeats), s.label)
        if piece.duration <= budget + 1e-6 and piece.duration >= MIN_PIECE_BARS * bar - 1e-6:
            picked.append(piece)
            budget -= piece.duration
    leftover_bars = int(budget / bar)
    rest = [s for s in cands if not any(abs(p.src_start - _snap(s.start_sec, downbeats)) < 1e-3 for p in picked)]
    if leftover_bars >= MIN_PIECE_BARS and rest:
        s = rest[0]
        start = _snap(s.start_sec, downbeats)
        end = min(_snap(s.end_sec, downbeats), _snap(start + leftover_bars * bar, downbeats))
        picked.append(SongPiece(start, end, s.label))
    return picked


def plan_music_edit(structure: SongStructure, *, needed_sec: float) -> list[SongPiece]:
    """Intro (<= 8 bars) + fill sections + final high-energy run through the song's ending."""
    segs = [s for s in structure.segments if s.label != "start"]
    downbeats, bar = structure.downbeats, structure.bar_sec
    if not segs or len(downbeats) < 2:
        raise ValueError("song structure has no sections or downbeats")
    intro = next((s for s in segs if s.label == "intro"), segs[0])
    intro_start = _snap(intro.start_sec, downbeats)
    intro_end = _snap(min(intro.end_sec, intro_start + INTRO_MAX_BARS * bar), downbeats)
    a, b = _finale_block(segs)
    finale_start = _snap(segs[a].start_sec, downbeats)
    tail = segs[b + 1] if b + 1 < len(segs) and segs[b + 1].label in ENDING_LABELS else None
    finale_end = tail.end_sec if tail is not None else _snap(segs[b].end_sec, downbeats)
    budget = needed_sec - (intro_end - intro_start) - (finale_end - finale_start)
    if budget < 0:
        keep = max(MIN_PIECE_BARS * bar, needed_sec - (intro_end - intro_start))
        finale_start = _snap(max(finale_start, finale_end - keep), downbeats)
        body: list[SongPiece] = []
    else:
        body = _body_pieces(segs, downbeats, intro_end, finale_start, budget, bar)
    pieces = [SongPiece(intro_start, intro_end, intro.label), *body, SongPiece(finale_start, finale_end, segs[b].label)]
    return _merge_contiguous(sorted(pieces, key=lambda p: p.src_start))


def _merge_contiguous(pieces: list[SongPiece]) -> list[SongPiece]:
    out: list[SongPiece] = []
    for p in pieces:
        if out and p.src_start <= out[-1].src_end + 1e-3:
            prev = out[-1]
            out[-1] = SongPiece(prev.src_start, max(prev.src_end, p.src_end), prev.label)
        else:
            out.append(p)
    return out


def remap_time(t: float, pieces: list[SongPiece]) -> float | None:
    """Source song time -> edited time; None when ``t`` was cut out."""
    offset = 0.0
    for i, p in enumerate(pieces):
        last = i == len(pieces) - 1
        if p.src_start - 1e-6 <= t < p.src_end or (last and abs(t - p.src_end) < 1e-6):
            return offset + (t - p.src_start)
        offset += p.duration
    return None


def remap_structure(structure: SongStructure, pieces: list[SongPiece]) -> SongStructure:
    beats = [e for e in (remap_time(t, pieces) for t in structure.beats) if e is not None]
    downbeats = [e for e in (remap_time(t, pieces) for t in structure.downbeats) if e is not None]
    segments: list[SongSegment] = []
    offset = 0.0
    for p in pieces:
        for s in structure.segments:
            lo, hi = max(s.start_sec, p.src_start), min(s.end_sec, p.src_end)
            if hi - lo > 1e-3:
                segments.append(SongSegment(offset + lo - p.src_start, offset + hi - p.src_start, s.label))
        offset += p.duration
    return SongStructure(bpm=structure.bpm, beats=beats, downbeats=downbeats, segments=segments)


def _truncate_structure(structure: SongStructure, end_sec: float) -> SongStructure:
    """Keep beats/sections that fall inside a contiguous [0, end_sec] window."""
    end = max(0.0, float(end_sec))
    return SongStructure(
        bpm=structure.bpm,
        beats=[float(b) for b in structure.beats if float(b) <= end + 1e-6],
        downbeats=[float(d) for d in structure.downbeats if float(d) <= end + 1e-6],
        segments=[
            SongSegment(float(s.start_sec), min(float(s.end_sec), end), str(s.label))
            for s in structure.segments
            if float(s.start_sec) < end - 1e-6
        ],
    )


def render_contiguous_track(audio_path: Path, out_path: Path, *, duration_sec: float) -> Path:
    """Export a single uninterrupted prefix of the song (no section teleports)."""
    song = load_audio_segment(audio_path)
    end_ms = max(1, min(len(song), int(round(float(duration_sec) * 1000))))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    song[:end_ms].export(str(out_path), format="wav")
    log.info("music_edit: contiguous %.1fs -> %s (no splices)", end_ms / 1000.0, out_path.name)
    return out_path


def render_music_edit(
    audio_path: Path, pieces: list[SongPiece], out_path: Path, *, xfade_ms: int | None = None
) -> Path:
    """Concatenate pieces with length-preserving crossfades centered on each splice."""
    song = load_audio_segment(audio_path)
    xfade = int(SPLICE_XFADE_MS if xfade_ms is None else xfade_ms)
    half = max(0, xfade // 2)
    out = None
    for i, p in enumerate(pieces):
        lead = half if i > 0 else 0
        trail = half if i < len(pieces) - 1 else 0
        start_ms = max(0, int(round(p.src_start * 1000)) - lead)
        end_ms = min(len(song), int(round(p.src_end * 1000)) + trail)
        chunk = song[start_ms:end_ms]
        out = chunk if out is None else out.append(chunk, crossfade=2 * half)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.export(str(out_path), format="wav")
    log.info(
        "music_edit: %d pieces -> %.1fs xfade=%dms %s",
        len(pieces),
        len(out) / 1000.0,
        xfade,
        [(round(p.src_start, 1), round(p.src_end, 1), p.label) for p in pieces],
    )
    return out_path


def prepare_edited_track(
    audio_path: Path,
    *,
    cache_dir: Path,
    needed_sec: float,
    xfade_ms: int | None = None,
    splice: bool = False,
):
    """Prepare the montage music bed and its BeatMap.

    Default ``splice=False``: play the song A→Z as a contiguous prefix of
    ``needed_sec`` (intro→verse→chorus in order). No section teleports.

    ``splice=True``: legacy intro + high-energy body + ending stitch (can jump).
    """
    from src.pipeline.beat_analyzer import analyze_beats, beat_map_from_structure
    from src.pipeline.song_structure import SongStructureError, analyze_song_structure

    try:
        structure = analyze_song_structure(audio_path, cache_dir=cache_dir)
        if not splice:
            # Pad slightly past target so fade-out / duration drift still has music.
            dur = max(float(needed_sec) + 2.0, float(needed_sec))
            edited = render_contiguous_track(
                audio_path, cache_dir / "music_contiguous.wav", duration_sec=dur
            )
            truncated = _truncate_structure(structure, dur)
            return edited, beat_map_from_structure(edited, truncated)
        pieces = plan_music_edit(structure, needed_sec=float(needed_sec))
        edited = render_music_edit(
            audio_path, pieces, cache_dir / "music_edit.wav", xfade_ms=xfade_ms
        )
        return edited, beat_map_from_structure(edited, remap_structure(structure, pieces))
    except (SongStructureError, ValueError, OSError) as exc:
        log.warning("prepare_edited_track: using the uncut song (%s)", exc)
        return audio_path, analyze_beats(audio_path)
