import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import db_session_with_rls, dispose_engine, platform_lookup_session
from app.models.invoice import Invoice, InvoiceStatus
from app.services.audit.audit_service import log_event
from app.services.dossier.document_ref_service import audit_document_detail, invoice_log_fields
from app.services.ingest.graph_mail_folders import finalize_graph_messages, folder_moves_enabled
from app.services.ingest.mailbox_poll import poll_all_and_ingest, poll_mailbox_and_ingest
from app.services.invoice.pipeline import EmailIngestResult, process_invoice
from app.tenant_scoped import get_for_tenant
from app.utils.logger import configure_logging, get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

_last_run: str | None = None
# Per-tenant in-process pipeline activity (not a global lock).
_inline_active_tenants: set[uuid.UUID] = set()
_inline_active_unscoped = 0


def _mark_pipeline_enter(tenant_id: uuid.UUID | None) -> None:
    global _inline_active_unscoped
    if tenant_id is None:
        _inline_active_unscoped += 1
    else:
        _inline_active_tenants.add(tenant_id)


def _mark_pipeline_exit(tenant_id: uuid.UUID | None) -> None:
    global _inline_active_unscoped
    if tenant_id is None:
        _inline_active_unscoped = max(0, _inline_active_unscoped - 1)
    else:
        _inline_active_tenants.discard(tenant_id)


def is_inline_pipeline_active(*, tenant_id: uuid.UUID | None = None) -> bool:
    """True while an in-process invoice pipeline is running.

    When ``tenant_id`` is set, only that tenant's activity counts — mailbox
    polling for other tenants must not wait on unrelated work.
    """
    if tenant_id is not None:
        return tenant_id in _inline_active_tenants
    return bool(_inline_active_tenants) or _inline_active_unscoped > 0


def get_processing_status() -> dict[str, str | int | None]:
    celery_active = 0
    try:
        from celery import current_app

        inspect = current_app.control.inspect(timeout=0.8)
        active = inspect.active() if inspect else None
        celery_active = sum(len(t or []) for t in (active or {}).values())
    except Exception:
        pass

    inline_count = len(_inline_active_tenants) + _inline_active_unscoped
    running = celery_active > 0 or inline_count > 0
    return {
        "state": "running" if running else "idle",
        "last_run": _last_run,
        "active_tasks": celery_active + inline_count,
    }


def _pipeline_error_message(exc: BaseException) -> str:
    text = str(exc).strip()
    if text:
        return text
    return f"{type(exc).__name__}"


_PENDING_STATUSES = [
    InvoiceStatus.PENDING,
    InvoiceStatus.PARSING,
    InvoiceStatus.VALIDATING,
    InvoiceStatus.MAPPING,
    InvoiceStatus.JOURNALING,
    InvoiceStatus.RECONCILING,
]

_TERMINAL_STATUSES = frozenset(
    {
        InvoiceStatus.PROCESSED,
        InvoiceStatus.DUPLICATE_SKIPPED,
        InvoiceStatus.REJECTED,
    }
)


async def _resolve_invoice_tenant_id(
    invoice_id: int,
    tenant_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if tenant_id is not None:
        return tenant_id
    async with platform_lookup_session() as session:
        inv = await session.get(Invoice, invoice_id)
        return inv.tenant_id if inv is not None else None


async def _fetch_pending_ids(*, tenant_id: uuid.UUID | None = None) -> list[int]:
    if tenant_id is None:
        return []
    async with db_session_with_rls(tenant_id) as session:
        stmt = select(Invoice.id).where(
            Invoice.tenant_id == tenant_id,
            Invoice.status.in_(_PENDING_STATUSES),
        )
        return list((await session.execute(stmt)).scalars().all())


async def process_invoice_by_id(
    invoice_id: int,
    *,
    tenant_id: uuid.UUID | None = None,
) -> bool:
    """Run the pipeline for one invoice (upload / reprocess)."""
    resolved_tid = await _resolve_invoice_tenant_id(invoice_id, tenant_id)
    if resolved_tid is None:
        return False

    ok = False
    async with db_session_with_rls(resolved_tid) as session:
        inv = await get_for_tenant(session, Invoice, invoice_id, resolved_tid)
        if inv is None:
            return False
        try:
            await process_invoice(session, inv)
            ok = True
        except Exception as exc:
            await session.rollback()
            error_message = _pipeline_error_message(exc)
            logger.error(
                "pipeline_error",
                error=error_message,
                invoice_id=invoice_id,
                exc_info=True,
            )
            async with db_session_with_rls(resolved_tid) as err_session:
                inv = await get_for_tenant(err_session, Invoice, invoice_id, resolved_tid)
                if (
                    inv
                    and inv.status in _PENDING_STATUSES
                    and inv.status not in _TERMINAL_STATUSES
                ):
                    inv.status = InvoiceStatus.EXCEPTION
                    await log_event(
                        err_session,
                        "pipeline_error",
                        invoice_id=invoice_id,
                        tenant_id=resolved_tid,
                        detail=audit_document_detail(inv, error=error_message),
                    )

    from app.services.dossier.dossier_reprocess_service import flush_scheduled_sibling_reprocess

    await flush_scheduled_sibling_reprocess()
    return ok


async def process_invoice_background(
    invoice_id: int,
    *,
    tenant_id: uuid.UUID | None = None,
) -> None:
    """FastAPI background task — must be async (uvicorn already has a running loop)."""
    global _last_run

    resolved_tid = await _resolve_invoice_tenant_id(invoice_id, tenant_id)
    lock = await _invoice_pipeline_lock(invoice_id)
    async with lock:
        _mark_pipeline_enter(resolved_tid)
        try:
            await _run_invoice_pipeline(invoice_id, tenant_id=tenant_id)
        finally:
            _mark_pipeline_exit(resolved_tid)
            _last_run = datetime.now(timezone.utc).isoformat()


async def process_invoices_batch_background(
    invoice_ids: list[int],
    *,
    tenant_id: uuid.UUID | None = None,
) -> None:
    """Process uploaded invoices with a small concurrency limit.

    Yields between invoices so uvicorn can keep serving HTTP while SYNC_PROCESSING
    runs in the same process.
    """
    global _last_run

    settings = get_settings()
    limit = max(1, int(settings.invoice_pipeline_concurrency))
    sem = asyncio.Semaphore(limit)
    _mark_pipeline_enter(tenant_id)
    try:

        async def _one(invoice_id: int) -> None:
            async with sem:
                lock = await _invoice_pipeline_lock(invoice_id)
                async with lock:
                    await _run_invoice_pipeline(invoice_id, tenant_id=tenant_id)
                # Let pending HTTP / health requests run between heavy pipelines.
                await asyncio.sleep(0)

        await asyncio.gather(*(_one(invoice_id) for invoice_id in invoice_ids))
    finally:
        _mark_pipeline_exit(tenant_id)
        _last_run = datetime.now(timezone.utc).isoformat()


def _parse_tenant_id(tenant_id: uuid.UUID | str | None) -> uuid.UUID | None:
    if tenant_id is None:
        return None
    if isinstance(tenant_id, uuid.UUID):
        return tenant_id
    return uuid.UUID(str(tenant_id))


def _try_enqueue_celery_invoices(
    invoice_ids: list[int],
    *,
    tenant_id: uuid.UUID,
) -> bool:
    """Enqueue Celery invoice tasks when SYNC_PROCESSING is off. Returns True on success."""
    settings = get_settings()
    if settings.sync_processing:
        return False
    try:
        tid = str(tenant_id)
        if len(invoice_ids) == 1:
            process_invoice_task.delay(invoice_ids[0], tenant_id=tid)
        else:
            process_invoices_batch_task.delay(invoice_ids, tenant_id=tid)
        return True
    except Exception as exc:
        logger.warning(
            "celery_invoice_enqueue_failed",
            error=str(exc),
            invoice_count=len(invoice_ids),
        )
        return False


async def queue_invoices_for_processing(
    invoice_ids: list[int],
    *,
    tenant_id: uuid.UUID,
) -> None:
    """Queue pipeline runs for ingested invoices (webhooks / async ingest)."""
    unique_ids = list(dict.fromkeys(invoice_ids))
    if not unique_ids:
        return
    if _try_enqueue_celery_invoices(unique_ids, tenant_id=tenant_id):
        return
    if len(unique_ids) == 1:
        asyncio.create_task(
            process_invoice_background(unique_ids[0], tenant_id=tenant_id),
            name=f"invoice-pipeline-{unique_ids[0]}",
        )
        return
    asyncio.create_task(
        process_invoices_batch_background(unique_ids, tenant_id=tenant_id),
        name=f"invoice-pipeline-batch-{unique_ids[0]}",
    )


def enqueue_invoice_pipelines(
    invoice_ids: list[int],
    *,
    tenant_id: uuid.UUID,
    background_tasks=None,
) -> str:
    """Shared enqueue for upload/reprocess APIs. Returns queued|running|idle."""
    unique_ids = list(dict.fromkeys(invoice_ids))
    if not unique_ids:
        return "idle"
    if _try_enqueue_celery_invoices(unique_ids, tenant_id=tenant_id):
        return "queued"
    if background_tasks is not None:
        if len(unique_ids) == 1:
            background_tasks.add_task(
                process_invoice_background, unique_ids[0], tenant_id=tenant_id
            )
        else:
            background_tasks.add_task(
                process_invoices_batch_background, unique_ids, tenant_id=tenant_id
            )
        return "running"
    # Fire-and-forget when no FastAPI BackgroundTasks (e.g. tests / scripts).
    if len(unique_ids) == 1:
        asyncio.create_task(
            process_invoice_background(unique_ids[0], tenant_id=tenant_id),
            name=f"invoice-pipeline-{unique_ids[0]}",
        )
    else:
        asyncio.create_task(
            process_invoices_batch_background(unique_ids, tenant_id=tenant_id),
            name=f"invoice-pipeline-batch-{unique_ids[0]}",
        )
    return "running"


_invoice_locks: dict[int, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _invoice_pipeline_lock(invoice_id: int) -> asyncio.Lock:
    async with _locks_guard:
        lock = _invoice_locks.get(invoice_id)
        if lock is None:
            lock = asyncio.Lock()
            _invoice_locks[invoice_id] = lock
        return lock


async def _run_invoice_pipeline(
    invoice_id: int,
    *,
    tenant_id: uuid.UUID | None = None,
) -> None:
    resolved_tid = await _resolve_invoice_tenant_id(invoice_id, tenant_id)
    if resolved_tid is None:
        logger.warning("invoice_pipeline_missing_tenant", invoice_id=invoice_id)
        return

    async with db_session_with_rls(resolved_tid) as session:
        inv = await get_for_tenant(session, Invoice, invoice_id, resolved_tid)
    if inv is None:
        return
    logger.info("invoice_pipeline_started", **invoice_log_fields(inv))
    await process_invoice_by_id(invoice_id, tenant_id=resolved_tid)
    async with db_session_with_rls(resolved_tid) as session:
        inv = await get_for_tenant(session, Invoice, invoice_id, resolved_tid)
    if inv is not None:
        logger.info("invoice_pipeline_finished", **invoice_log_fields(inv))


def process_invoice_by_id_sync(invoice_id: int, *, tenant_id: uuid.UUID | None = None) -> None:
    """Celery / CLI entry only — not for FastAPI BackgroundTasks."""
    configure_logging(get_settings().log_level)

    async def _run() -> None:
        await process_invoice_background(invoice_id, tenant_id=tenant_id)

    asyncio.run(_run())


@celery_app.task(
    bind=True,
    name="app.workers.tasks.process_invoice_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
)
def process_invoice_task(
    self,
    invoice_id: int,
    tenant_id: uuid.UUID | str | None = None,
) -> dict[str, object]:
    """Celery entry for a single invoice pipeline (keeps uvicorn free)."""
    configure_logging(get_settings().log_level)
    tid = _parse_tenant_id(tenant_id)
    logger.info(
        "process_invoice_task_started",
        task_id=self.request.id,
        invoice_id=invoice_id,
        tenant_id=str(tid) if tid else None,
    )

    async def run_with_cleanup() -> bool:
        try:
            await process_invoice_background(invoice_id, tenant_id=tid)
            return True
        finally:
            await dispose_engine()

    ok = asyncio.run(run_with_cleanup())
    return {"invoice_id": invoice_id, "ok": ok}


@celery_app.task(
    bind=True,
    name="app.workers.tasks.process_invoices_batch_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
)
def process_invoices_batch_task(
    self,
    invoice_ids: list[int],
    tenant_id: uuid.UUID | str | None = None,
) -> dict[str, object]:
    """Celery entry for concurrent batch invoice pipelines."""
    configure_logging(get_settings().log_level)
    tid = _parse_tenant_id(tenant_id)
    unique_ids = list(dict.fromkeys(invoice_ids))
    logger.info(
        "process_invoices_batch_task_started",
        task_id=self.request.id,
        invoice_count=len(unique_ids),
        tenant_id=str(tid) if tid else None,
    )

    async def run_with_cleanup() -> None:
        try:
            await process_invoices_batch_background(unique_ids, tenant_id=tid)
        finally:
            await dispose_engine()

    asyncio.run(run_with_cleanup())
    return {"invoice_ids": unique_ids, "ok": True}


async def _process_pending(
    invoice_ids: list[int],
    *,
    tenant_id: uuid.UUID | None = None,
) -> int:
    if not invoice_ids:
        return 0
    settings = get_settings()
    limit = max(1, int(settings.invoice_pipeline_concurrency))
    sem = asyncio.Semaphore(limit)
    processed = 0
    lock = asyncio.Lock()

    async def _one(invoice_id: int) -> None:
        nonlocal processed
        async with sem:
            pipeline_lock = await _invoice_pipeline_lock(invoice_id)
            async with pipeline_lock:
                ok = await process_invoice_by_id(invoice_id, tenant_id=tenant_id)
            if ok:
                async with lock:
                    processed += 1

    await asyncio.gather(*(_one(invoice_id) for invoice_id in invoice_ids))
    return processed


async def run_pipeline(
    *,
    mailbox_id: int | None = None,
    tenant_id: uuid.UUID | None = None,
    poll_inbox: bool = False,
    skip_pending_check: bool = False,
) -> dict[str, int]:
    """Poll mailboxes (optional) and process pending invoices.

    ``skip_pending_check``: when True, skip the pre-poll pending sweep so a
    mailbox-only cycle is not coupled to unrelated invoice-processing load.
    Newly ingested mail is still processed after the poll.
    """
    if tenant_id is None:
        return {"ingested": 0, "processed": 0}

    processed = 0
    if not skip_pending_check:
        processed = await _process_pending(
            await _fetch_pending_ids(tenant_id=tenant_id),
            tenant_id=tenant_id,
        )

    ingested = 0
    message_ids: list[str] = []
    preskip: dict[str, str] = {}
    message_mailboxes: dict[str, str] = {}
    message_graph_ids: dict[str, str] = {}

    if mailbox_id is not None:
        async with db_session_with_rls(tenant_id) as session:
            ingest_result = await poll_mailbox_and_ingest(
                session, mailbox_id=mailbox_id, tenant_id=tenant_id
            )
            ingested = ingest_result.ingested_count
            message_ids = ingest_result.message_ids
            preskip = ingest_result.preskip_exceptions
            message_mailboxes = ingest_result.message_mailbox_emails
            message_graph_ids = ingest_result.message_graph_ids
    elif poll_inbox:
        async with db_session_with_rls(tenant_id) as session:
            ingest_result = await poll_all_and_ingest(session, tenant_id=tenant_id)
            ingested = ingest_result.ingested_count
            message_ids = ingest_result.message_ids
            preskip = ingest_result.preskip_exceptions
            message_mailboxes = ingest_result.message_mailbox_emails
            message_graph_ids = ingest_result.message_graph_ids
    else:
        ingest_result = EmailIngestResult()

    # Always process newly ingested mail. Invoice-level locks prevent double-runs;
    # do not couple mailbox latency to a pre-poll sweep of unrelated pending work.
    if ingested:
        processed += await _process_pending(
            await _fetch_pending_ids(tenant_id=tenant_id),
            tenant_id=tenant_id,
        )

    if message_ids:
        async with db_session_with_rls(tenant_id) as session:
            moved = await finalize_graph_messages(
                session,
                message_ids,
                tenant_id=tenant_id,
                preskip_exceptions=preskip,
                message_mailbox_emails=message_mailboxes,
                message_graph_ids=message_graph_ids,
            )
            logger.info(
                "graph_messages_finalized",
                moved=moved,
                total=len(message_ids),
                folder_moves=folder_moves_enabled(),
            )

    return {"ingested": ingested, "processed": processed}


async def run_pipeline_background(
    *,
    mailbox_id: int | None = None,
    tenant_id: uuid.UUID | None = None,
    poll_inbox: bool = False,
) -> None:
    """FastAPI background task — must be async (uvicorn already has a running loop)."""
    global _last_run

    _mark_pipeline_enter(tenant_id)
    try:
        logger.info(
            "inline_pipeline_started",
            mailbox_id=mailbox_id,
            tenant_id=str(tenant_id) if tenant_id else None,
            poll_inbox=poll_inbox,
        )
        result = await run_pipeline(
            mailbox_id=mailbox_id,
            tenant_id=tenant_id,
            poll_inbox=poll_inbox,
        )
        logger.info("inline_pipeline_done", **result)
    except Exception as exc:
        logger.error(
            "inline_pipeline_failed",
            mailbox_id=mailbox_id,
            tenant_id=str(tenant_id) if tenant_id else None,
            error=str(exc),
        )
    finally:
        _mark_pipeline_exit(tenant_id)
        _last_run = datetime.now(timezone.utc).isoformat()


def run_pipeline_sync(
    *,
    mailbox_id: int | None = None,
    tenant_id: uuid.UUID | None = None,
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
        from app.database import async_session_factory
        from app.services.tenant.tenant_context_service import (
            list_active_tenant_ids_with_mailboxes,
        )

        totals = {"ingested": 0, "processed": 0}
        try:
            async with async_session_factory() as session:
                tenant_ids = await list_active_tenant_ids_with_mailboxes(session)
            settings = get_settings()
            concurrency = max(1, int(settings.mailbox_poll_concurrency))
            sem = asyncio.Semaphore(concurrency)
            lock = asyncio.Lock()

            async def _one(tid: uuid.UUID) -> None:
                async with sem:
                    result = await run_pipeline(
                        tenant_id=tid,
                        poll_inbox=True,
                        skip_pending_check=True,
                    )
                    async with lock:
                        totals["ingested"] += result.get("ingested", 0)
                        totals["processed"] += result.get("processed", 0)

            await asyncio.gather(*(_one(tid) for tid in tenant_ids))
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
def process_inbox_task(
    self,
    mailbox_id: int | None = None,
    tenant_id: uuid.UUID | None = None,
) -> dict[str, int]:
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


async def run_mailbox_backfill_background(
    job_id: int,
    *,
    tenant_id: uuid.UUID | None = None,
) -> None:
    """FastAPI background task entry for historical mailbox import."""
    global _last_run

    _mark_pipeline_enter(tenant_id)
    try:
        from app.services.ingest.mailbox_backfill_service import run_mailbox_backfill_job

        logger.info("mailbox_backfill_started", job_id=job_id, tenant_id=str(tenant_id))
        await run_mailbox_backfill_job(job_id, tenant_id=tenant_id)
    finally:
        _mark_pipeline_exit(tenant_id)
        _last_run = datetime.now(timezone.utc).isoformat()


def run_mailbox_backfill_sync(job_id: int, *, tenant_id: uuid.UUID | None = None) -> None:
    configure_logging(get_settings().log_level)

    async def _run() -> None:
        try:
            await run_mailbox_backfill_background(job_id, tenant_id=tenant_id)
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
def mailbox_backfill_task(
    self,
    job_id: int,
    tenant_id: uuid.UUID | None = None,
) -> dict[str, object]:
    global _last_run
    configure_logging(get_settings().log_level)
    logger.info("mailbox_backfill_task_started", task_id=self.request.id, job_id=job_id)

    async def run_with_cleanup() -> dict[str, object]:
        try:
            from app.services.ingest.mailbox_backfill_service import run_mailbox_backfill_job

            job = await run_mailbox_backfill_job(job_id, tenant_id=tenant_id)
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
