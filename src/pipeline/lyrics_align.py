"""Music-aware lyric / hook events: vocals → word times → hooks → beat snap.

Default path (when deps are present):
  1. Demucs vocal stem (cached)
  2. faster-whisper word timestamps (lyrics sheet as prompt when known)
  3. Match hook phrases ("hand clap", …)
  4. Snap each hook onset to the nearest beat

Falls back to chorus-section stubs only if ASR/Demucs are unavailable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
from pathlib import Path

from src.pipeline.beat_analyzer import BeatMap
from src.pipeline.lyric_sheets import HANDCLAP_LYRICS, HOOK_PHRASES

log = logging.getLogger(__name__)

_HOOK_SECTION = frozenset({"chorus", "drop", "inst", "solo"})
_ASR_MODEL = "small"
_MAX_HOOKS = 16
_BEAT_SNAP_SEC = 0.12


def _stem_key(song_title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (song_title or "").lower()).strip()


def _lyrics_prompt(song_title: str) -> str:
    key = _stem_key(song_title)
    if "handclap" in key.replace(" ", "") or "hand clap" in key:
        return HANDCLAP_LYRICS
    return ""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]+", " ", (text or "").lower()).strip()


def _cache_key(audio_path: Path) -> str:
    st = audio_path.stat()
    # Size-only fingerprint: contiguous wav is rewritten often with identical bytes,
    # and mtime thrashing would force redundant Demucs/ASR every pipeline run.
    raw = f"{audio_path.name}|{st.st_size}|{_ASR_MODEL}|vad0"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _separate_vocals(audio_path: Path, cache_dir: Path) -> Path | None:
    """Demucs htdemucs → vocals.wav under cache_dir. Returns None on failure."""
    out_root = cache_dir / "demucs"
    # demucs writes out_root/htdemucs/<stem>/vocals.wav
    stem = audio_path.stem
    expected = out_root / "htdemucs" / stem / "vocals.wav"
    if expected.is_file() and expected.stat().st_size > 1000:
        return expected
    out_root.mkdir(parents=True, exist_ok=True)
    try:
        import demucs.separate  # noqa: F401 — ensure importable
    except ImportError:
        log.info("lyrics_align: demucs not installed")
        return None
    import sys

    cmd = [
        sys.executable,
        "-m",
        "demucs",
        "-n",
        "htdemucs",
        "--two-stems",
        "vocals",
        "-o",
        str(out_root),
        str(audio_path),
    ]
    try:
        log.info("lyrics_align: demucs separating vocals for %s", audio_path.name)
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=900)
        if proc.stderr:
            log.debug("lyrics_align: demucs stderr: %s", proc.stderr[-500:])
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or "")[-400:]
        log.warning("lyrics_align: demucs failed (%s)%s; using full mix for ASR", exc, f" :: {detail}" if detail else "")
        return None
    if expected.is_file():
        return expected
    # demucs may sanitize stem names
    matches = list((out_root / "htdemucs").glob("*/vocals.wav"))
    return matches[0] if matches else None


def _transcribe_words(audio_path: Path, *, lyrics_prompt: str) -> list[tuple[float, str]]:
    """Return [(start_sec, word), ...] via faster-whisper."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log.info("lyrics_align: faster-whisper not installed")
        return []
    device = "cuda"
    compute = "float16"
    try:
        model = WhisperModel(_ASR_MODEL, device=device, compute_type=compute)
    except Exception:
        model = WhisperModel(_ASR_MODEL, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        # Music vocals trip Silero VAD — it can drop the whole track (seen on HandClap).
        vad_filter=False,
        condition_on_previous_text=False,
        language="en",
        initial_prompt=(lyrics_prompt.strip()[:220] or None),
    )
    words: list[tuple[float, str]] = []
    for seg in segments:
        for w in seg.words or []:
            token = _norm(getattr(w, "word", "") or "")
            if not token:
                continue
            words.append((float(w.start), token))
    return words


def _find_hooks(words: list[tuple[float, str]]) -> list[tuple[float, str]]:
    """Scan the word stream for known hook n-grams; return (onset, DISPLAY TEXT)."""
    if not words:
        return []
    tokens = [w for _, w in words]
    times = [t for t, _ in words]
    joined = tokens  # already normalized
    out: list[tuple[float, str]] = []
    i = 0
    while i < len(joined):
        matched = False
        # Longer phrases first.
        for phrase in sorted(HOOK_PHRASES, key=len, reverse=True):
            parts = phrase.split()
            n = len(parts)
            if i + n > len(joined):
                continue
            window = " ".join(joined[i : i + n])
            if window == phrase or window.replace(" ", "") == phrase.replace(" ", ""):
                display = phrase.upper()
                out.append((times[i], display))
                i += n
                matched = True
                break
        if not matched:
            i += 1
    # De-dupe hooks that fire within 1.5s of each other (same chant).
    deduped: list[tuple[float, str]] = []
    for t, line in out:
        if deduped and abs(t - deduped[-1][0]) < 1.5 and deduped[-1][1] == line:
            continue
        deduped.append((t, line))
    return deduped[:_MAX_HOOKS]


def _snap_to_beats(events: list[tuple[float, str]], beat_map: BeatMap | None) -> list[tuple[float, str]]:
    beats = list(getattr(beat_map, "beat_times", None) or []) if beat_map else []
    if not beats:
        return events
    snapped: list[tuple[float, str]] = []
    for t, line in events:
        nearest = min(beats, key=lambda b: abs(float(b) - t))
        if abs(float(nearest) - t) <= _BEAT_SNAP_SEC:
            snapped.append((float(nearest), line))
        else:
            snapped.append((t, line))
    return snapped


def hooks_from_structure(
    beat_map: BeatMap | None, *, song_title: str, max_events: int = 8
) -> list[tuple[float, str]]:
    """Legacy fallback: known phrases on chorus/drop section starts (NOT word-accurate)."""
    if beat_map is None:
        return []
    key = _stem_key(song_title)
    phrases = ("HAND CLAP", "PUT YOUR HANDS UP", "HAND CLAP")
    if "handclap" not in key.replace(" ", "") and "hand clap" not in key:
        phrases = ("LET'S GO",)
    onsets = [
        float(s.start_sec)
        for s in (beat_map.sections or [])
        if str(s.section_type) in _HOOK_SECTION and float(s.start_sec) > 0.4
    ]
    return [(t, phrases[i % len(phrases)]) for i, t in enumerate(onsets[:max_events])]


def _load_cache(path: Path) -> list[tuple[float, str]] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [(float(x["t"]), str(x["line"])) for x in data.get("hooks", [])]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _save_cache(path: Path, hooks: list[tuple[float, str]], *, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"source": source, "hooks": [{"t": t, "line": line} for t, line in hooks]}, indent=2),
        encoding="utf-8",
    )


def analyze_lyric_events(
    audio_path: Path | None,
    beat_map: BeatMap | None,
    *,
    song_title: str,
    prefer_asr: bool = True,
    cache_dir: Path | None = None,
) -> list[tuple[float, str]]:
    """Timed lyric/hook lines for overlays (song / montage time)."""
    cache_dir = cache_dir or (Path(audio_path).parent if audio_path else Path("."))
    if prefer_asr and audio_path is not None and Path(audio_path).is_file():
        audio_path = Path(audio_path)
        cache_file = cache_dir / f"lyrics_hooks_{_cache_key(audio_path)}.json"
        cached = _load_cache(cache_file)
        if cached is not None:
            log.info("lyrics_align: loaded %d cached ASR hooks", len(cached))
            return _snap_to_beats(cached, beat_map)

        asr_src = _separate_vocals(audio_path, cache_dir) or audio_path
        words = _transcribe_words(asr_src, lyrics_prompt=_lyrics_prompt(song_title))
        hooks = _find_hooks(words)
        if hooks:
            hooks = _snap_to_beats(hooks, beat_map)
            _save_cache(cache_file, hooks, source="asr")
            log.info(
                "lyrics_align: %d ASR hooks from %s -> %s",
                len(hooks),
                asr_src.name,
                [(round(t, 2), line) for t, line in hooks],
            )
            return hooks
        log.warning("lyrics_align: ASR produced no hook phrases; falling back to structure")

    events = hooks_from_structure(beat_map, song_title=song_title)
    log.info("lyrics_align: %d structure hook events for %r", len(events), song_title)
    return events
