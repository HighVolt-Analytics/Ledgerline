from celery import Celery
from celery.schedules import crontab

from app.azure_env import celery_redis_ssl_options
from app.config import get_settings

s = get_settings()

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
        "task": "app.workers.tasks.process_inbox_task",
        "schedule": _poll_schedule,
    },
}
