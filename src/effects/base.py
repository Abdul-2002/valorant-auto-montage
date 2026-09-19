from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol


class VideoClipLike(Protocol):
    duration: float


@dataclass(frozen=True)
class EffectContext:
    clip: Any
    kill_timestamp: float | None
    beat_timestamp: float | None
    clip_duration: float
    fps: int
    resolution: tuple[int, int]
    config: dict[str, Any]
    # Seconds on the output / music timeline (post script phase trim), for audio effects.
    kill_timestamps: tuple[float, ...] = ()


class ClipEffect(ABC):
    name: str

    @abstractmethod
    def apply(self, ctx: EffectContext) -> Any:
        raise NotImplementedError

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "ClipEffect":
        return cls(**config)  # type: ignore[arg-type]


class TransitionEffect(ABC):
    name: str

    @abstractmethod
    def apply(self, clip_a: Any, clip_b: Any, duration: float, *, offset: float | None = None) -> Any:
        raise NotImplementedError

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "TransitionEffect":
        # Transitions are configured from `TransitionsConfig`, but individual transition
        # classes generally accept only a small subset of those keys. Filter unknown keys
        # so selecting a non-`hard_cut` default doesn't crash at runtime.
        try:
            import inspect

            params = inspect.signature(cls).parameters
            allowed = {k for k in params.keys() if k != "self"}
            filtered = {k: v for k, v in (config or {}).items() if k in allowed}
            return cls(**filtered)  # type: ignore[arg-type]
        except Exception:
            # Conservative fallback: best-effort construction.
            return cls()  # type: ignore[call-arg]


class AudioEffect(ABC):
    name: str

    @abstractmethod
    def apply(self, audio: Any, ctx: EffectContext) -> Any:
        raise NotImplementedError

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "AudioEffect":
        return cls(**config)  # type: ignore[arg-type]
