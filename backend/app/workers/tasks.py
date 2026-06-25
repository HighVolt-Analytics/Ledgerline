import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_factory, dispose_engine
from app.models.invoice import Invoice, InvoiceStatus
from app.services.audit_service import log_event
from app.services.document_ref_service import audit_document_detail, invoice_log_fields
from app.services.graph_mail_folders import finalize_graph_messages, folder_moves_enabled
from app.services.mailbox_poll import poll_all_and_ingest, poll_mailbox_and_ingest
from app.services.pipeline import EmailIngestResult, process_invoice
from app.utils.logger import configure_logging, get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

_last_run: str | None = None
_inline_active = False

_PENDING_STATUSES = [
    InvoiceStatus.PENDING,
    InvoiceStatus.PARSING,
    InvoiceStatus.VALIDATING,
    InvoiceStatus.MAPPING,
    InvoiceStatus.JOURNALING,
    InvoiceStatus.RECONCILING,
]


def get_processing_status() -> dict[str, str | int | None]:
    celery_active = 0
    try:
        from celery import current_app

        inspect = current_app.control.inspect(timeout=0.8)
        active = inspect.active() if inspect else None
        celery_active = sum(len(t or []) for t in (active or {}).values())
    except Exception:
        pass

    running = celery_active > 0 or _inline_active
    return {
        "state": "running" if running else "idle",
        "last_run": _last_run,
        "active_tasks": celery_active + (1 if _inline_active else 0),
    }


async def _fetch_pending_ids(*, tenant_id: int | None = None) -> list[int]:
    async with async_session_factory() as session:
        stmt = select(Invoice.id).where(Invoice.status.in_(_PENDING_STATUSES))
        if tenant_id is not None:
            stmt = stmt.where(Invoice.tenant_id == tenant_id)
        return list((await session.execute(stmt)).scalars().all())


async def process_invoice_by_id(invoice_id: int) -> bool:
    """Run the pipeline for one invoice (upload / reprocess)."""
    async with async_session_factory() as session:
        inv = await session.get(Invoice, invoice_id)
        if inv is None:
            return False
        try:
            await process_invoice(session, inv)
            await session.commit()
            return True
        except Exception as exc:
            await session.rollback()
            logger.error("pipeline_error", error=str(exc), invoice_id=invoice_id)
            async with async_session_factory() as err_session:
                inv = await err_session.get(Invoice, invoice_id)
                if inv and inv.status in _PENDING_STATUSES:
                    inv.status = InvoiceStatus.EXCEPTION
                    await log_event(
                        err_session,
                        "pipeline_error",
                        invoice_id=invoice_id,
                        detail=audit_document_detail(inv, error=str(exc)),
                    )
                    await err_session.commit()
            return False


async def process_invoice_background(invoice_id: int) -> None:
    """FastAPI background task — must be async (uvicorn already has a running loop)."""
    global _last_run, _inline_active

    lock = await _invoice_pipeline_lock(invoice_id)
    async with lock:
        _inline_active = True
        try:
            await _run_invoice_pipeline(invoice_id)
        finally:
            _inline_active = False
            _last_run = datetime.now(timezone.utc).isoformat()


async def process_invoices_batch_background(invoice_ids: list[int]) -> None:
    """Process uploaded invoices one at a time (bulk upload)."""
    global _last_run, _inline_active

    _inline_active = True
    try:
        for invoice_id in invoice_ids:
            lock = await _invoice_pipeline_lock(invoice_id)
            async with lock:
                await _run_invoice_pipeline(invoice_id)
    finally:
        _inline_active = False
        _last_run = datetime.now(timezone.utc).isoformat()


_invoice_locks: dict[int, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _invoice_pipeline_lock(invoice_id: int) -> asyncio.Lock:
    async with _locks_guard:
        lock = _invoice_locks.get(invoice_id)
        if lock is None:
            lock = asyncio.Lock()
            _invoice_locks[invoice_id] = lock
        return lock


async def _run_invoice_pipeline(invoice_id: int) -> None:
    async with async_session_factory() as session:
        inv = await session.get(Invoice, invoice_id)
    logger.info("invoice_pipeline_started", **invoice_log_fields(inv))
    await process_invoice_by_id(invoice_id)
    async with async_session_factory() as session:
        inv = await session.get(Invoice, invoice_id)
    logger.info("invoice_pipeline_finished", **invoice_log_fields(inv))


def process_invoice_by_id_sync(invoice_id: int) -> None:
    """Celery / CLI entry only — not for FastAPI BackgroundTasks."""
    configure_logging(get_settings().log_level)

    async def _run() -> None:
        await process_invoice_background(invoice_id)

    asyncio.run(_run())


async def _process_pending(invoice_ids: list[int]) -> int:
    processed = 0
    for invoice_id in invoice_ids:
        lock = await _invoice_pipeline_lock(invoice_id)
        async with lock:
            if await process_invoice_by_id(invoice_id):
                processed += 1
    return processed


async def run_pipeline(
    *,
    mailbox_id: int | None = None,
    tenant_id: int | None = None,
    poll_inbox: bool = False,
) -> dict[str, int]:
    """Poll mailboxes (optional) and process pending invoices."""
    processed = await _process_pending(await _fetch_pending_ids(tenant_id=tenant_id))

    ingested = 0
    message_ids: list[str] = []
    preskip: dict[str, str] = {}

    if mailbox_id is not None and tenant_id is not None:
        async with async_session_factory() as session:
            ingest_result = await poll_mailbox_and_ingest(
                session, mailbox_id=mailbox_id, tenant_id=tenant_id
            )
            await session.commit()
            ingested = ingest_result.ingested_count
            message_ids = ingest_result.message_ids
            preskip = ingest_result.preskip_exceptions
    elif poll_inbox:
        async with async_session_factory() as session:
            ingest_result = await poll_all_and_ingest(session, tenant_id=tenant_id)
            await session.commit()
            ingested = ingest_result.ingested_count
            message_ids = ingest_result.message_ids
            preskip = ingest_result.preskip_exceptions
    else:
        ingest_result = EmailIngestResult()

    if ingested:
        processed += await _process_pending(await _fetch_pending_ids(tenant_id=tenant_id))

    if message_ids and folder_moves_enabled():
        async with async_session_factory() as session:
            moved = await finalize_graph_messages(
                session,
                message_ids,
                tenant_id=tenant_id,
                preskip_exceptions=preskip,
            )
            await session.commit()
            logger.info("graph_messages_finalized", moved=moved, total=len(message_ids))

    return {"ingested": ingested, "processed": processed}


async def run_pipeline_background(
    *,
    mailbox_id: int | None = None,
    tenant_id: int | None = None,
    poll_inbox: bool = False,
) -> None:
    """FastAPI background task — must be async (uvicorn already has a running loop)."""
    global _last_run, _inline_active

    _inline_active = True
    try:
        logger.info(
            "inline_pipeline_started",
            mailbox_id=mailbox_id,
            tenant_id=tenant_id,
            poll_inbox=poll_inbox,
        )
        result = await run_pipeline(
            mailbox_id=mailbox_id,
            tenant_id=tenant_id,
            poll_inbox=poll_inbox,
        )
        logger.info("inline_pipeline_done", **result)
    finally:
        _inline_active = False
        _last_run = datetime.now(timezone.utc).isoformat()


def run_pipeline_sync(
    *,
    mailbox_id: int | None = None,
    tenant_id: int | None = None,
    poll_inbox: bool = False,
    dispose_pool: bool = False,
) -> dict[str, int]:
    """CLI / script entry — not for FastAPI BackgroundTasks."""
    configure_logging(get_settings().log_level)

    async def _run() -> dict[str, int]:
        try:
            return await run_pipeline(
                mailbox_id=mailbox_id,
                tenant_id=tenant_id,
                poll_inbox=poll_inbox,
            )
        finally:
            if dispose_pool:
                await dispose_engine()

    return asyncio.run(_run())


@celery_app.task(
    bind=True,
    name="app.workers.tasks.poll_all_tenants_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def poll_all_tenants_task(self) -> dict[str, int]:
    """Fan out inbox polling per active tenant."""
    global _last_run
    configure_logging(get_settings().log_level)
    logger.info("poll_all_tenants_started", task_id=self.request.id)

    async def run_with_cleanup() -> dict[str, int]:
        from app.services.tenant_context_service import list_active_tenant_ids

        totals = {"ingested": 0, "processed": 0}
        try:
            async with async_session_factory() as session:
                tenant_ids = await list_active_tenant_ids(session)
            for tid in tenant_ids:
                result = await run_pipeline(tenant_id=tid, poll_inbox=True)
                totals["ingested"] += result.get("ingested", 0)
                totals["processed"] += result.get("processed", 0)
            return totals
        finally:
            await dispose_engine()

    result = asyncio.run(run_with_cleanup())
    _last_run = datetime.now(timezone.utc).isoformat()
    logger.info("poll_all_tenants_done", **result)
    return result


@celery_app.task(
    bind=True,
    name="app.workers.tasks.process_inbox_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def process_inbox_task(self, mailbox_id: int | None = None, tenant_id: int | None = None) -> dict[str, int]:
    global _last_run
    configure_logging(get_settings().log_level)
    logger.info("task_started", task_id=self.request.id, mailbox_id=mailbox_id)

    async def run_with_cleanup() -> dict[str, int]:
        try:
            return await run_pipeline(
                mailbox_id=mailbox_id,
                tenant_id=tenant_id,
                poll_inbox=True,
            )
        finally:
            await dispose_engine()

    result = asyncio.run(run_with_cleanup())
    _last_run = datetime.now(timezone.utc).isoformat()
    logger.info("task_done", **result)
    return result


async def run_mailbox_backfill_background(job_id: int) -> None:
    """FastAPI background task entry for historical mailbox import."""
    global _last_run, _inline_active

    _inline_active = True
    try:
        from app.services.mailbox_backfill_service import run_mailbox_backfill_job

        logger.info("mailbox_backfill_started", job_id=job_id)
        await run_mailbox_backfill_job(job_id)
    finally:
        _inline_active = False
        _last_run = datetime.now(timezone.utc).isoformat()


def run_mailbox_backfill_sync(job_id: int) -> None:
    configure_logging(get_settings().log_level)

    async def _run() -> None:
        try:
            await run_mailbox_backfill_background(job_id)
        finally:
            await dispose_engine()

    asyncio.run(_run())


@celery_app.task(
    bind=True,
    name="app.workers.tasks.mailbox_backfill_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
)
def mailbox_backfill_task(self, job_id: int) -> dict[str, object]:
    global _last_run
    configure_logging(get_settings().log_level)
    logger.info("mailbox_backfill_task_started", task_id=self.request.id, job_id=job_id)

    async def run_with_cleanup() -> dict[str, object]:
        try:
            from app.services.mailbox_backfill_service import run_mailbox_backfill_job

            job = await run_mailbox_backfill_job(job_id)
            return {
                "job_id": job.id,
                "status": job.status,
                "attachments_ingested": job.attachments_ingested,
            }
        finally:
            await dispose_engine()

    result = asyncio.run(run_with_cleanup())
    _last_run = datetime.now(timezone.utc).isoformat()
    logger.info("mailbox_backfill_task_done", **result)
    return result
