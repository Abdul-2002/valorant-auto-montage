from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path

from src.library.errors import LibraryError

log = logging.getLogger(__name__)

_GENERATE_TIMEOUT_SEC = 180.0
_ACTIVE_WAIT_SEC = 300.0

_SUMMARY_PROMPT = """Summarize this Valorant gameplay video so a later montage can reuse the description without watching the file again.
Return JSON with keys:
summary: string, 2 to 4 sentences
maps: array of map names, empty if unknown
agents: array of agent names seen
notable_plays: array of short strings, each with an approximate timestamp in seconds and what happened
Ignore menus and loading screens."""


def generate_video_summary(path: Path, *, api_key: str, model: str) -> str:
    """Upload once with the existing Gemini file helper, store nothing remote."""
    if not api_key.strip():
        raise LibraryError("GEMINI_API_KEY is not set")
    client, uploaded = _upload(path, api_key=api_key)
    try:
        active = _wait_until_active(client, uploaded)
        return _generate(client, active, model)
    finally:
        _delete_remote(client, getattr(uploaded, "name", ""))


def _upload(path: Path, *, api_key: str) -> tuple[object, object]:
    try:
        from google import genai
    except Exception as exc:
        raise LibraryError("google-genai is not installed") from exc
    from src.detection.gemini_video import _upload_path_for
    client = genai.Client(api_key=api_key)
    upload_path, _proxy = _upload_path_for(Path(path))
    try:
        uploaded = client.files.upload(file=str(upload_path))
    except Exception as exc:
        raise LibraryError(f"Gemini file upload failed ({type(exc).__name__})") from None
    return client, uploaded


def _wait_until_active(client: object, uploaded: object) -> object:
    import time

    name = getattr(uploaded, "name", "")
    deadline = time.monotonic() + _ACTIVE_WAIT_SEC
    while True:
        current = client.files.get(name=name)  # type: ignore[attr-defined]
        state = str(getattr(current, "state", "")).upper()
        if "ACTIVE" in state:
            return current
        if "FAILED" in state:
            raise LibraryError(f"Gemini file processing failed ({state})")
        if time.monotonic() > deadline:
            raise LibraryError("Gemini file did not become ACTIVE")
        time.sleep(5)


def _generate(client: object, active: object, model: str) -> str:
    names = [model]
    if model != "gemini-2.5-flash-lite":
        names.append("gemini-2.5-flash-lite")
    last = "no response"
    for name in names:
        try:
            return _generate_once(client, active, name)
        except Exception as exc:
            last = type(exc).__name__
            log.warning("video summary model %s failed: %s", name, last)
    raise LibraryError(f"Gemini summary failed ({last})")


def _generate_once(client: object, active: object, model: str) -> str:
    def _call() -> object:
        return client.models.generate_content(  # type: ignore[attr-defined]
            model=model,
            contents=[active, _SUMMARY_PROMPT],
            config={"response_mime_type": "application/json"},
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            response = pool.submit(_call).result(timeout=_GENERATE_TIMEOUT_SEC)
        except FuturesTimeout as exc:
            raise LibraryError("Gemini summary timed out") from exc
    text = str(getattr(response, "text", None) or "").strip()
    if not text:
        raise LibraryError("Gemini returned an empty summary")
    return text


def _delete_remote(client: object, name: str) -> None:
    if not name:
        return
    try:
        client.files.delete(name=name)  # type: ignore[attr-defined]
    except Exception:
        log.warning("Gemini summary file was not deleted (%s)", name)
