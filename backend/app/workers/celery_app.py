from celery import Celery
from celery.schedules import crontab
from kombu import Queue

from app.azure_env import celery_redis_ssl_options
from app.config import get_settings

s = get_settings()
_BASE_QUEUE = s.celery_task_queue_resolved
_INVOICE_QUEUE = s.celery_invoice_queue_resolved
_MAILBOX_QUEUE = s.celery_mailbox_queue_resolved

celery_app = Celery(
    "invoice_pipeline",
    broker=s.celery_broker_url,
    backend=s.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_default_retry_delay=60,
    task_max_retries=3,
    task_default_queue=_INVOICE_QUEUE,
    task_queues=(
        Queue(_INVOICE_QUEUE),
        Queue(_MAILBOX_QUEUE),
        Queue(_BASE_QUEUE),  # legacy drain for pre-split deployments
    ),
    task_routes={
        "app.workers.tasks.process_invoice_task": {"queue": _INVOICE_QUEUE},
        "app.workers.tasks.process_invoices_batch_task": {"queue": _INVOICE_QUEUE},
        "app.workers.tasks.requeue_stuck_pending_task": {"queue": _INVOICE_QUEUE},
        "app.workers.tasks.poll_all_tenants_task": {"queue": _MAILBOX_QUEUE},
        "app.workers.tasks.process_inbox_task": {"queue": _MAILBOX_QUEUE},
        "app.workers.tasks.mailbox_backfill_task": {"queue": _MAILBOX_QUEUE},
    },
    task_create_missing_queues=True,
    **celery_redis_ssl_options(s.celery_broker_url, s.celery_result_backend),
)

_poll_mins = s.graph_poll_interval_minutes
_poll_schedule = (
    crontab(minute="*")
    if _poll_mins == 1
    else crontab(minute=f"*/{_poll_mins}")
)

celery_app.conf.beat_schedule = {
    "poll-inbox": {
        "task": "app.workers.tasks.poll_all_tenants_task",
        "schedule": _poll_schedule,
        "options": {"queue": _MAILBOX_QUEUE},
    },
    # Mail poll uses skip_pending_check=True; this recovers orphaned PENDING rows.
    "requeue-stuck-pending": {
        "task": "app.workers.tasks.requeue_stuck_pending_task",
        "schedule": crontab(minute="*/2"),
        "options": {"queue": _INVOICE_QUEUE},
    },
}
