from __future__ import annotations

import os

from celery import Celery


def _broker_url() -> str:
    return os.environ.get("REDIS_BROKER_URL", "redis://localhost:6379/0")


def _backend_url() -> str:
    return os.environ.get("REDIS_BACKEND_URL", "redis://localhost:6379/1")

try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    pass


celery_app = Celery(
    "valorant_montage_bot",
    broker=_broker_url(),
    backend=_backend_url(),
    include=["src.worker.tasks"],
)
celery_app.conf.task_track_started = True
celery_app.conf.result_expires = 60 * 60 * 24
