"""Celery application instance.

Run a worker with:
    celery -A app.workers.celery_app:celery worker --loglevel=info
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery = Celery(
    "radonaix",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
)
