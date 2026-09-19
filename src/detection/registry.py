from __future__ import annotations

import importlib
import pkgutil
from typing import Type

from src.detection.base import Detector

_detectors: dict[str, Type[Detector]] = {}
_discovered = False


def register_detector(name: str):
    def decorator(cls: Type[Detector]) -> Type[Detector]:
        _detectors[name] = cls
        cls.name = name
        return cls

    return decorator


def discover_detectors() -> None:
    global _discovered
    if _discovered:
        return

    import src.detection as detect_pkg

    for _, module_name, _ in pkgutil.iter_modules(detect_pkg.__path__):
        importlib.import_module(f"src.detection.{module_name}")

    _discovered = True


def get_detector(name: str) -> Type[Detector]:
    discover_detectors()
    return _detectors[name]


def list_detectors() -> list[str]:
    discover_detectors()
    return sorted(_detectors.keys())
