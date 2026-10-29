"""Bound the number of live ffmpeg decoders while a montage renders.

MoviePy keeps one ffmpeg subprocess per VideoFileClip for the whole render
(~300 MB each on 1080p120 DVR footage), so a 22-clip montage OOMs a 6 GB
container. Only one or two clips are read at a time; closing idle readers is
safe because MoviePy's FFMPEG_VideoReader re-initialises itself at ``t`` when
``get_frame`` finds no process.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any


class DecoderPool:
    def __init__(self, limit: int = 4) -> None:
        if limit < 1:
            raise ValueError(f"decoder pool limit must be >= 1, got {limit}")
        self._limit = limit
        self._live: OrderedDict[Any, None] = OrderedDict()

    @property
    def live_count(self) -> int:
        return len(self._live)

    def track(self, reader: Any) -> None:
        """Route ``reader.get_frame`` through the pool and count the reader as live."""
        get_frame = reader.get_frame

        def pooled_get_frame(t: float) -> Any:
            self._touch(reader)
            return get_frame(t)

        reader.get_frame = pooled_get_frame
        self._touch(reader)

    def _touch(self, reader: Any) -> None:
        self._live[reader] = None
        self._live.move_to_end(reader)
        while len(self._live) > self._limit:
            idle, _ = self._live.popitem(last=False)
            idle.close()
