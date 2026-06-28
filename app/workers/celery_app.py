from celery import Celery

from app.config import get_settings

settings = get_settings()

# ── Celery Application ─────────────────────────────────────────────────────────
# include: tells Celery where to auto-discover task definitions on startup.
# This avoids having to manually register each task.
celery_app = Celery(
    "medisync",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Timezone
    timezone="Asia/Kolkata",
    enable_utc=True,

    # Task routing — each module gets its own queue for isolation
    task_routes={
        "app.workers.tasks.analyze_symptom_report": {"queue": "triage"},
    },

    # Result expiration — keep task results for 24 hours
    result_expires=86400,

    # Retry policy defaults
    task_acks_late=True,          # Acknowledge task only after it completes
    task_reject_on_worker_lost=True,  # Re-queue if worker dies mid-task
)
