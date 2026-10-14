from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from src.ai.enrichment import EnrichedEvent
from src.ai.schema import CreativeBrief
from src.pipeline.beat_analyzer import BeatMap


@dataclass(frozen=True)
class BriefContext:
    enriched_events: list[EnrichedEvent]
    beat_map: BeatMap | None
    creative_config_resolved: dict[str, Any]
    model_hint: str | None = None
    # Timed lyric/hook lines (song time) from the music-understanding layer.
    lyric_events: tuple[tuple[float, str], ...] = ()
    # Optional per-event play class from multimodal review: ace|clutch|op|"".
    play_labels: dict[int, str] | None = None


class BriefProvider(ABC):
    @abstractmethod
    def generate_brief(self, ctx: BriefContext) -> CreativeBrief | None:
        raise NotImplementedError
