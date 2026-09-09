"""Auto-push processed AP bills to Xero after the invoice transaction commits.

Search (contact + tax) and POST happen only when Xero is connected. Failures
never raise into invoice processing.

Must be awaited after commit. Fire-and-forget create_task is dropped when the
Celery worker's asyncio.run() loop closes, which left Acc sync Pending forever.

When Xero was disconnected, processed AP bills stay Acc sync Pending. Connecting
(or selecting the organisation) replays those invoices in id order.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting_export_ledger import (
    STATUS_SUCCESS,
    AccountingExportLedger,
    PROVIDER_XERO,
)
from app.models.invoice import Invoice, InvoiceStatus
from app.utils.logger import get_logger

logger = get_logger(__name__)

_INFO_KEY = "ledgerlink_xero_auto_push"
_replay_locks: dict[str, asyncio.Lock] = {}


def _ap_invoice_eligible(invoice: Any) -> bool:
    from app.services.classification.document_type_playbook_profile_service import (
        gl_posting_applicable_for_invoice,
    )
    from app.services.invoice.invoice_evaluation_service import ROUTE_SALES, ROUTE_VAULT

    if getattr(invoice, "id", None) is None:
        return False
    if invoice.status != InvoiceStatus.PROCESSED:
        return False
    if not gl_posting_applicable_for_invoice(invoice):
        return False
    route = (getattr(invoice, "route_target", None) or "").strip()
    return route not in {ROUTE_SALES, ROUTE_VAULT}


def _session_info(session: Any) -> dict[str, Any]:
    sync = getattr(session, "sync_session", None)
    if sync is not None:
        return sync.info
    return session.info


def schedule_xero_auto_push(session: Any, invoice: Any) -> None:
    """Queue a Xero DRAFT export for after this session commits."""
    if not _ap_invoice_eligible(invoice):
        return
    info = _session_info(session)
    jobs: list[tuple[str, int]] = info.setdefault(_INFO_KEY, [])
    item = (str(invoice.tenant_id), int(invoice.id))
    if item not in jobs:
        jobs.append(item)


def take_scheduled_xero_auto_push(session: Any) -> list[tuple[str, int]]:
    return list(_session_info(session).pop(_INFO_KEY, []) or [])


async def flush_scheduled_xero_auto_push(session: Any) -> None:
    """Run queued exports after a successful commit. Safe to call when empty.

    Also drains other Acc-sync-pending processed AP bills for the same tenant so
    older documents are forwarded to Xero without running the invoice pipeline again.
    """
    jobs = take_scheduled_xero_auto_push(session)
    tenant_keys = {tenant_key for tenant_key, _invoice_id in jobs}
    for tenant_key, invoice_id in jobs:
        await run_scheduled_xero_auto_push(uuid.UUID(tenant_key), invoice_id)
    for tenant_key in tenant_keys:
        await replay_pending_xero_exports(uuid.UUID(tenant_key))


async def run_scheduled_xero_auto_push(tenant_id: uuid.UUID, invoice_id: int) -> dict[str, Any] | None:
    """New session: match/create contact (already done) then export DRAFT. Never raises."""
    from app.database import db_session_with_rls
    from app.integrations.xero.export import XeroExportError, export_supplier_invoice_to_xero
    from app.integrations.xero.store import require_xero_ready

    try:
        async with db_session_with_rls(tenant_id) as db:
            try:
                await require_xero_ready(db, tenant_id)
            except Exception:
                logger.info(
                    "xero_auto_push_skipped_not_connected",
                    invoice_id=invoice_id,
                    tenant_id=str(tenant_id),
                )
                return None
            invoice = await db.get(Invoice, invoice_id)
            if (
                invoice is None
                or invoice.tenant_id != tenant_id
                or not _ap_invoice_eligible(invoice)
            ):
                return None
            try:
                result = await export_supplier_invoice_to_xero(
                    db,
                    tenant_id=tenant_id,
                    invoice_id=invoice_id,
                    user_id=None,
                )
                logger.info(
                    "xero_auto_push_ok",
                    invoice_id=invoice_id,
                    skipped=result.get("skipped"),
                    external_id=(result.get("evidence") or {}).get("external_id"),
                )
                return result
            except XeroExportError as exc:
                logger.warning(
                    "xero_auto_push_export_failed",
                    invoice_id=invoice_id,
                    tenant_id=str(tenant_id),
                    code=exc.code,
                    error=str(exc),
                    blocking=exc.blocking_errors,
                )
                return None
            except Exception:
                logger.warning(
                    "xero_auto_push_export_failed",
                    invoice_id=invoice_id,
                    tenant_id=str(tenant_id),
                    exc_info=True,
                )
                return None
    except Exception:
        logger.warning(
            "xero_auto_push_session_failed",
            invoice_id=invoice_id,
            tenant_id=str(tenant_id),
            exc_info=True,
        )
        return None


async def list_pending_xero_auto_push_invoice_ids(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[int]:
    """Processed AP invoices for this tenant with no successful Xero export."""
    success_exists = (
        select(AccountingExportLedger.id)
        .where(
            AccountingExportLedger.tenant_id == tenant_id,
            AccountingExportLedger.provider == PROVIDER_XERO,
            AccountingExportLedger.source_invoice_id == Invoice.id,
            AccountingExportLedger.status == STATUS_SUCCESS,
        )
        .exists()
    )
    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.status == InvoiceStatus.PROCESSED,
            ~success_exists,
        )
        .order_by(Invoice.id.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [int(inv.id) for inv in rows if _ap_invoice_eligible(inv)]


async def replay_pending_xero_exports(tenant_id: uuid.UUID) -> dict[str, int]:
    """Push Acc-sync-pending processed AP bills now that this tenant's Xero org is ready.

    Never raises. Skips when Xero is not connected. Sequential per tenant so a
    connect callback and Integrations page cannot POST the same bill twice at once.
    """
    from app.database import db_session_with_rls
    from app.integrations.xero.store import require_xero_ready

    key = str(tenant_id)
    lock = _replay_locks.setdefault(key, asyncio.Lock())
    async with lock:
        attempted = 0
        succeeded = 0
        try:
            async with db_session_with_rls(tenant_id) as db:
                try:
                    await require_xero_ready(db, tenant_id)
                except Exception:
                    logger.info(
                        "xero_pending_replay_skipped_not_connected",
                        tenant_id=key,
                    )
                    return {
                        "attempted": 0,
                        "succeeded": 0,
                        "skipped_not_connected": 1,
                    }
                invoice_ids = await list_pending_xero_auto_push_invoice_ids(db, tenant_id)
            for invoice_id in invoice_ids:
                attempted += 1
                result = await run_scheduled_xero_auto_push(tenant_id, invoice_id)
                if result is not None:
                    succeeded += 1
            logger.info(
                "xero_pending_replay_done",
                tenant_id=key,
                attempted=attempted,
                succeeded=succeeded,
            )
            return {
                "attempted": attempted,
                "succeeded": succeeded,
                "skipped_not_connected": 0,
            }
        except Exception:
            logger.warning(
                "xero_pending_replay_failed",
                tenant_id=key,
                attempted=attempted,
                succeeded=succeeded,
                exc_info=True,
            )
            return {
                "attempted": attempted,
                "succeeded": succeeded,
                "skipped_not_connected": 0,
            }


async def list_connected_xero_tenant_ids() -> list[uuid.UUID]:
    from app.database import async_session_factory
    from app.models.accounting_integration import (
        AccountingIntegration,
        AccountingIntegrationStatus,
        AccountingProvider,
    )

    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(AccountingIntegration.tenant_id)
                .where(
                    AccountingIntegration.provider == AccountingProvider.XERO.value,
                    AccountingIntegration.status == AccountingIntegrationStatus.CONNECTED.value,
                )
                .distinct()
            )
        ).all()
    return [row[0] for row in rows]


async def replay_pending_xero_for_connected_tenants() -> dict[str, int]:
    """Export Acc-sync-pending processed AP bills for every connected Xero tenant.

    Does not re-run extraction, GL journal, or change invoice status.
    """
    tenants = 0
    attempted = 0
    succeeded = 0
    try:
        tenant_ids = await list_connected_xero_tenant_ids()
    except Exception:
        logger.warning("xero_pending_replay_list_tenants_failed", exc_info=True)
        return {"tenants": 0, "attempted": 0, "succeeded": 0}
    for tenant_id in tenant_ids:
        tenants += 1
        result = await replay_pending_xero_exports(tenant_id)
        attempted += int(result.get("attempted") or 0)
        succeeded += int(result.get("succeeded") or 0)
    if tenants:
        logger.info(
            "xero_pending_replay_connected_tenants_done",
            tenants=tenants,
            attempted=attempted,
            succeeded=succeeded,
        )
    return {"tenants": tenants, "attempted": attempted, "succeeded": succeeded}


_PENDING_REPLAY_POLL_SECONDS = 120
_pending_replay_task: asyncio.Task[Any] | None = None


async def _pending_replay_loop() -> None:
    await asyncio.sleep(8)
    while True:
        try:
            await replay_pending_xero_for_connected_tenants()
        except Exception:
            logger.warning("xero_pending_replay_loop_failed", exc_info=True)
        await asyncio.sleep(_PENDING_REPLAY_POLL_SECONDS)


def start_xero_pending_export_replay() -> asyncio.Task[Any] | None:
    global _pending_replay_task
    if _pending_replay_task is not None and not _pending_replay_task.done():
        return _pending_replay_task
    _pending_replay_task = asyncio.create_task(
        _pending_replay_loop(),
        name="xero-pending-export-replay",
    )
    logger.info("xero_pending_export_replay_started")
    return _pending_replay_task


async def stop_xero_pending_export_replay() -> None:
    global _pending_replay_task
    if _pending_replay_task is None:
        return
    _pending_replay_task.cancel()
    try:
        await _pending_replay_task
    except asyncio.CancelledError:
        pass
    _pending_replay_task = None
    logger.info("xero_pending_export_replay_stopped")
