"""Celery application instance.

Configures the broker/backend from ``Settings``, enforces single-task
concurrency (FR-07.3 — avoid GPU memory conflicts), and enables
``task_acks_late`` so crashed workers re-queue the task automatically.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from podletters.config import get_settings

settings = get_settings()

app = Celery("podletters")

app.conf.update(
    broker_url=settings.celery_broker_url,
    result_backend=settings.celery_result_backend,

    # One task at a time — GPU is a shared resource (PRD §5.7, FR-07.3).
    worker_prefetch_multiplier=1,
    worker_concurrency=1,

    # Re-queue on worker crash (PRD §5.7).
    task_acks_late=True,

    # Serialization: JSON for debuggability.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Timezone-aware scheduling.
    timezone="UTC",
    enable_utc=True,

    # ── Celery Beat schedule (Task 26 / FR-07.1) ──────────────────
    beat_schedule={
        "poll-imap-for-newsletters": {
            "task": "podletters.ingest_email",
            "schedule": settings.poll_interval_seconds,  # default 900s
        },
    },

    # ── Default retry policy (Task 27 / FR-07.2) ─────────────────
    # Individual tasks can override via decorator kwargs.
    task_default_retry_delay=60,        # 60 s initial delay
    task_max_retries=3,                 # then dead-letter
)

# Auto-discover task modules.
app.autodiscover_tasks(["podletters"])
