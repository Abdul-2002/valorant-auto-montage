from .models import AppConfig


def __getattr__(name: str):
    if name == "load_config":
        from .loader import load_config

        return load_config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["AppConfig", "load_config"]
