"""Celery queue isolation for shared Redis brokers."""

from __future__ import annotations

from app.config import Settings


def test_celery_queue_production() -> None:
    s = Settings(APP_ENV="production", ENVIRONMENT="production")
    assert s.celery_task_queue_resolved == "ledgerlink.production"


def test_celery_queue_staging_app_env_ledgerlink() -> None:
    s = Settings(APP_ENV="ledgerlink", ENVIRONMENT="")
    assert s.celery_task_queue_resolved == "ledgerlink.staging"


def test_celery_queue_local_keeps_default() -> None:
    s = Settings(APP_ENV="development", ENVIRONMENT="")
    assert s.celery_task_queue_resolved == "celery"
