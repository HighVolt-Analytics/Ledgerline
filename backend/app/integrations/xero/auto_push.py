"""Auto-push processed AP bills to Xero after the invoice transaction commits.

Search (contact + tax) and POST happen only when Xero is connected. Failures
never raise into invoice processing.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.invoice import Invoice, InvoiceStatus
from app.utils.logger import get_logger

logger = get_logger(__name__)

_INFO_KEY = "ledgerlink_xero_auto_push"
_LISTENER_ATTACHED = False


def _ap_invoice_eligible(invoice: Any) -> bool:
    from app.services.invoice.invoice_evaluation_service import ROUTE_SALES, ROUTE_VAULT

    if getattr(invoice, "id", None) is None:
        return False
    if invoice.status != InvoiceStatus.PROCESSED:
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


def _after_commit_auto_push(session: Session) -> None:
    jobs = session.info.pop(_INFO_KEY, None)
    if not jobs:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("xero_auto_push_no_event_loop", jobs=len(jobs))
        return
    for tenant_key, invoice_id in jobs:
        loop.create_task(
            run_scheduled_xero_auto_push(uuid.UUID(tenant_key), invoice_id),
            name=f"xero-auto-push-{invoice_id}",
        )


def ensure_auto_push_listener() -> None:
    global _LISTENER_ATTACHED
    if _LISTENER_ATTACHED:
        return
    event.listen(Session, "after_commit", _after_commit_auto_push)
    _LISTENER_ATTACHED = True


ensure_auto_push_listener()


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
