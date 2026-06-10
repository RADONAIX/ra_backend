"""Celery application instance.

NOT YET ACTIVE: scaffolding for the planned async architecture. The only task
(`reports.generate`) is no longer enqueued by any endpoint, so the worker has
nothing to run today and the app functions without it. Activate when adding
background jobs (report generation, pipeline triggers, scheduled tasks).

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
