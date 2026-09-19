from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class DetectionContext:
    video_index: int
    video_path: Path
    assets_dir: Path
    config: dict[str, Any]


class Detector(ABC):
    name: str

    @abstractmethod
    def detect(self, ctx: DetectionContext) -> list[dict[str, Any]]:
        """
        Return a list of raw event dicts.

        Must include at least:
        - video_index: int
        - timestamp_sec: float
        - score: float (0..1)
        - event_type: str
        """

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "Detector":
        return cls(**config)  # type: ignore[arg-type]
