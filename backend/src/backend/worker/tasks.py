"""Celery task definitions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.worker.celery_app import celery_app


@celery_app.task(name="worker.ping")
def ping() -> dict[str, Any]:
    """Health-check task confirming the worker is active and processing."""
    return {"pong": True, "ts": datetime.now(UTC).isoformat()}
