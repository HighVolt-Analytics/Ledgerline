"""Celery queue isolation for shared Redis brokers."""

from __future__ import annotations

from app.config import Settings


def test_celery_queue_production() -> None:
    s = Settings(APP_ENV="production", ENVIRONMENT="production")
    assert s.celery_task_queue_resolved == "ledgerlink.production"
    assert s.celery_invoice_queue_resolved == "ledgerlink.production.invoices"
    assert s.celery_mailbox_queue_resolved == "ledgerlink.production.mailbox"
    assert s.celery_worker_queues_resolved == (
        "ledgerlink.production.invoices,ledgerlink.production.mailbox,ledgerlink.production"
    )


def test_celery_queue_staging_app_env_ledgerlink() -> None:
    s = Settings(APP_ENV="ledgerlink", ENVIRONMENT="")
    assert s.celery_task_queue_resolved == "ledgerlink.staging"
    assert s.celery_invoice_queue_resolved == "ledgerlink.staging.invoices"
    assert s.celery_mailbox_queue_resolved == "ledgerlink.staging.mailbox"


def test_celery_queue_local_keeps_default() -> None:
    s = Settings(APP_ENV="development", ENVIRONMENT="")
    assert s.celery_task_queue_resolved == "celery"
    assert s.celery_invoice_queue_resolved == "celery.invoices"
    assert s.celery_mailbox_queue_resolved == "celery.mailbox"


def test_celery_task_routes_split_invoice_and_mailbox() -> None:
    from app.workers.celery_app import celery_app

    routes = celery_app.conf.task_routes
    assert routes["app.workers.tasks.process_invoice_task"]["queue"].endswith(".invoices")
    assert routes["app.workers.tasks.poll_all_tenants_task"]["queue"].endswith(".mailbox")
