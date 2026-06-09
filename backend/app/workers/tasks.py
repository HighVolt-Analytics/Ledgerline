import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_factory, dispose_engine
from app.models.invoice import Invoice, InvoiceStatus
from app.services.audit_service import log_event
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


async def _fetch_pending_ids(*, org_id: int | None = None) -> list[int]:
    async with async_session_factory() as session:
        stmt = select(Invoice.id).where(Invoice.status.in_(_PENDING_STATUSES))
        if org_id is not None:
            stmt = stmt.where(Invoice.org_id == org_id)
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
            logger.error("pipeline_error", invoice_id=invoice_id, error=str(exc))
            async with async_session_factory() as err_session:
                inv = await err_session.get(Invoice, invoice_id)
                if inv and inv.status in _PENDING_STATUSES:
                    inv.status = InvoiceStatus.EXCEPTION
                    await log_event(
                        err_session,
                        "pipeline_error",
                        invoice_id=invoice_id,
                        detail={"error": str(exc)},
                    )
                    await err_session.commit()
            return False


async def process_invoice_background(invoice_id: int) -> None:
    """FastAPI background task — must be async (uvicorn already has a running loop)."""
    global _last_run, _inline_active

    _inline_active = True
    try:
        logger.info("invoice_pipeline_started", invoice_id=invoice_id)
        await process_invoice_by_id(invoice_id)
    finally:
        _inline_active = False
        _last_run = datetime.now(timezone.utc).isoformat()
        logger.info("invoice_pipeline_finished", invoice_id=invoice_id)


def process_invoice_by_id_sync(invoice_id: int) -> None:
    """Celery / CLI entry only — not for FastAPI BackgroundTasks."""
    configure_logging(get_settings().log_level)

    async def _run() -> None:
        await process_invoice_background(invoice_id)

    asyncio.run(_run())


async def _process_pending(invoice_ids: list[int]) -> int:
    processed = 0
    for invoice_id in invoice_ids:
        async with async_session_factory() as session:
            try:
                inv = await session.get(Invoice, invoice_id)
                if inv is None:
                    continue
                await process_invoice(session, inv)
                await session.commit()
                processed += 1
            except Exception as exc:
                await session.rollback()
                logger.error("pipeline_error", invoice_id=invoice_id, error=str(exc))
                async with async_session_factory() as err_session:
                    inv = await err_session.get(Invoice, invoice_id)
                    if inv and inv.status in _PENDING_STATUSES:
                        inv.status = InvoiceStatus.EXCEPTION
                        await log_event(
                            err_session,
                            "pipeline_error",
                            invoice_id=invoice_id,
                            detail={"error": str(exc)},
                        )
                        await err_session.commit()
    return processed


async def run_pipeline(
    *,
    mailbox_id: int | None = None,
    org_id: int | None = None,
    poll_inbox: bool = False,
) -> dict[str, int]:
    """Poll mailboxes (optional) and process pending invoices."""
    processed = await _process_pending(await _fetch_pending_ids(org_id=org_id))

    ingested = 0
    message_ids: list[str] = []
    preskip: dict[str, str] = {}

    if mailbox_id is not None and org_id is not None:
        async with async_session_factory() as session:
            ingest_result = await poll_mailbox_and_ingest(
                session, mailbox_id=mailbox_id, org_id=org_id
            )
            await session.commit()
            ingested = ingest_result.ingested_count
            message_ids = ingest_result.message_ids
            preskip = ingest_result.preskip_exceptions
    elif poll_inbox:
        async with async_session_factory() as session:
            ingest_result = await poll_all_and_ingest(session)
            await session.commit()
            ingested = ingest_result.ingested_count
            message_ids = ingest_result.message_ids
            preskip = ingest_result.preskip_exceptions
    else:
        ingest_result = EmailIngestResult()

    if ingested:
        processed += await _process_pending(await _fetch_pending_ids(org_id=org_id))

    if message_ids and folder_moves_enabled():
        async with async_session_factory() as session:
            moved = await finalize_graph_messages(
                session,
                message_ids,
                preskip_exceptions=preskip,
            )
            await session.commit()
            logger.info("graph_messages_finalized", moved=moved, total=len(message_ids))

    return {"ingested": ingested, "processed": processed}


async def run_pipeline_background(
    *,
    mailbox_id: int | None = None,
    org_id: int | None = None,
    poll_inbox: bool = False,
) -> None:
    """FastAPI background task — must be async (uvicorn already has a running loop)."""
    global _last_run, _inline_active

    _inline_active = True
    try:
        logger.info(
            "inline_pipeline_started",
            mailbox_id=mailbox_id,
            org_id=org_id,
            poll_inbox=poll_inbox,
        )
        result = await run_pipeline(
            mailbox_id=mailbox_id,
            org_id=org_id,
            poll_inbox=poll_inbox,
        )
        logger.info("inline_pipeline_done", **result)
    finally:
        _inline_active = False
        _last_run = datetime.now(timezone.utc).isoformat()


def run_pipeline_sync(
    *,
    mailbox_id: int | None = None,
    org_id: int | None = None,
    poll_inbox: bool = False,
    dispose_pool: bool = False,
) -> dict[str, int]:
    """CLI / script entry — not for FastAPI BackgroundTasks."""
    configure_logging(get_settings().log_level)

    async def _run() -> dict[str, int]:
        try:
            return await run_pipeline(
                mailbox_id=mailbox_id,
                org_id=org_id,
                poll_inbox=poll_inbox,
            )
        finally:
            if dispose_pool:
                await dispose_engine()

    return asyncio.run(_run())


@celery_app.task(
    bind=True,
    name="app.workers.tasks.process_inbox_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def process_inbox_task(self, mailbox_id: int | None = None, org_id: int | None = None) -> dict[str, int]:
    global _last_run
    configure_logging(get_settings().log_level)
    logger.info("task_started", task_id=self.request.id, mailbox_id=mailbox_id)

    async def run_with_cleanup() -> dict[str, int]:
        try:
            return await run_pipeline(
                mailbox_id=mailbox_id,
                org_id=org_id,
                poll_inbox=True,
            )
        finally:
            await dispose_engine()

    result = asyncio.run(run_with_cleanup())
    _last_run = datetime.now(timezone.utc).isoformat()
    logger.info("task_done", **result)
    return result
