from __future__ import annotations

import importlib
import pkgutil
from typing import Type

from src.effects.base import AudioEffect, ClipEffect, TransitionEffect

_clip_effects: dict[str, Type[ClipEffect]] = {}
_transition_effects: dict[str, Type[TransitionEffect]] = {}
_audio_effects: dict[str, Type[AudioEffect]] = {}
_discovered: bool = False


def register_clip_effect(name: str):
    def decorator(cls: Type[ClipEffect]) -> Type[ClipEffect]:
        _clip_effects[name] = cls
        cls.name = name
        return cls

    return decorator


def register_transition(name: str):
    def decorator(cls: Type[TransitionEffect]) -> Type[TransitionEffect]:
        _transition_effects[name] = cls
        cls.name = name
        return cls

    return decorator


def register_audio_effect(name: str):
    def decorator(cls: Type[AudioEffect]) -> Type[AudioEffect]:
        _audio_effects[name] = cls
        cls.name = name
        return cls

    return decorator


def discover_effects() -> None:
    global _discovered
    if _discovered:
        return

    import src.effects as effects_pkg

    for _, module_name, _ in pkgutil.iter_modules(effects_pkg.__path__):
        importlib.import_module(f"src.effects.{module_name}")

    # also import nested packages explicitly (transitions, audio)
    import src.effects.transitions as transitions_pkg
    import src.effects.audio as audio_pkg

    for _, module_name, _ in pkgutil.iter_modules(transitions_pkg.__path__):
        importlib.import_module(f"src.effects.transitions.{module_name}")

    for _, module_name, _ in pkgutil.iter_modules(audio_pkg.__path__):
        importlib.import_module(f"src.effects.audio.{module_name}")

    _discovered = True


def get_clip_effect(name: str) -> Type[ClipEffect]:
    discover_effects()
    return _clip_effects[name]


def get_transition(name: str) -> Type[TransitionEffect]:
    discover_effects()
    return _transition_effects[name]


def get_audio_effect(name: str) -> Type[AudioEffect]:
    discover_effects()
    return _audio_effects[name]


def list_clip_effects() -> list[str]:
    discover_effects()
    return sorted(_clip_effects.keys())


def list_transitions() -> list[str]:
    discover_effects()
    return sorted(_transition_effects.keys())


def list_audio_effects() -> list[str]:
    discover_effects()
    return sorted(_audio_effects.keys())
