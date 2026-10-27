"""Celery application instance.

Intentionally imports NO FastAPI components — this module is loaded in the
Celery worker process which runs separately from the API server.

Broker and result-backend URLs are derived from Settings as computed fields,
so REDIS_BASE_URL + REDIS_DB_CELERY_* are the single source of truth.
"""

from __future__ import annotations

from celery import Celery

from backend.core.config import settings

celery_app = Celery(
    "swarnbharat",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["backend.worker.tasks"],  # explicit include, no autodiscover
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,  # fair dispatch for long tasks
    task_acks_late=True,  # re-queue on worker crash
)
