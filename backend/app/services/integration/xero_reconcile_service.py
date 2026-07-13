"""Reconcile exported LedgerLink invoices with current Xero document state."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting_integration import AccountingProvider
from app.models.accounting_sync_job import JOB_TYPE_RECONCILE
from app.models.external_accounting_ref import ExternalAccountingRef
from app.services.integration.accounting_integration_service import require_xero_ready
from app.services.integration.xero_client import XeroApiError, XeroClient
from app.services.integration.xero_sync_job_service import (
    enqueue_sync_job,
    mark_job_completed,
    mark_job_failed,
    mark_job_running,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_PROVIDER = AccountingProvider.XERO.value


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


async def reconcile_external_ref(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    ref: ExternalAccountingRef,
    client: XeroClient | None = None,
) -> dict[str, Any]:
    if not ref.external_entity_id:
        raise ValueError("External reference has no Xero document ID")
    if client is None:
        _, xero_tenant_id = await require_xero_ready(db, tenant_id)
        client = XeroClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)

    payload = await client.get_json(
        "Invoices",
        params={"IDs": ref.external_entity_id},
    )
    invoices = payload.get("Invoices") or []
    if not invoices:
        ref.reconciliation_status = "missing_remote"
        ref.sync_error_code = "not_found"
        ref.sync_error_message = "Xero invoice not found"
        ref.last_reconciled_at = datetime.now(timezone.utc)
        await db.flush()
        return {"ref_id": ref.id, "status": "missing_remote"}

    inv = invoices[0]
    now = datetime.now(timezone.utc)
    ref.external_number = inv.get("InvoiceNumber") or ref.external_number
    ref.external_status = inv.get("Status") or ref.external_status
    ref.amount_due = _decimal(inv.get("AmountDue"))
    ref.amount_paid = _decimal(inv.get("AmountPaid"))
    status = str(inv.get("Status") or "").upper()
    amount_due = ref.amount_due or Decimal("0")
    ref.is_fully_paid = status == "PAID" or amount_due <= 0
    if status == "VOIDED":
        ref.reconciliation_status = "voided"
    elif ref.is_fully_paid:
        ref.reconciliation_status = "paid"
    else:
        ref.reconciliation_status = "open"
    ref.last_remote_modified_at = _parse_dt(inv.get("UpdatedDateUTC"))
    ref.last_reconciled_at = now
    ref.last_synced_at = now
    ref.sync_error_code = None
    ref.sync_error_message = None
    await db.flush()
    return {
        "ref_id": ref.id,
        "external_entity_id": ref.external_entity_id,
        "external_status": ref.external_status,
        "reconciliation_status": ref.reconciliation_status,
        "amount_due": float(ref.amount_due) if ref.amount_due is not None else None,
        "amount_paid": float(ref.amount_paid) if ref.amount_paid is not None else None,
        "is_fully_paid": ref.is_fully_paid,
        "last_reconciled_at": ref.last_reconciled_at,
    }


async def reconcile_pending(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    ref_id: int | None = None,
    trigger_type: str = "manual",
    initiated_by: int | None = None,
) -> dict[str, Any]:
    job = await enqueue_sync_job(
        db,
        tenant_id=tenant_id,
        job_type=JOB_TYPE_RECONCILE,
        direction="inbound",
        entity_type="invoice",
        trigger_type=trigger_type,
        initiated_by=initiated_by,
    )
    await mark_job_running(db, job)
    try:
        _, xero_tenant_id = await require_xero_ready(db, tenant_id)
        client = XeroClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
        stmt = select(ExternalAccountingRef).where(
            ExternalAccountingRef.tenant_id == tenant_id,
            ExternalAccountingRef.provider == _PROVIDER,
            ExternalAccountingRef.entity_type == "invoice",
            ExternalAccountingRef.external_entity_id != "",
        )
        if ref_id is not None:
            stmt = stmt.where(ExternalAccountingRef.id == ref_id)
        else:
            stmt = stmt.where(
                ExternalAccountingRef.sync_status.in_(["synced", "pushing", "failed", None])
            )
        rows = list((await db.execute(stmt.order_by(ExternalAccountingRef.id.asc()))).scalars())
        results: list[dict[str, Any]] = []
        failed = 0
        for ref in rows:
            try:
                results.append(
                    await reconcile_external_ref(
                        db,
                        tenant_id=tenant_id,
                        ref=ref,
                        client=client,
                    )
                )
            except (XeroApiError, ValueError, RuntimeError) as exc:
                failed += 1
                ref.sync_error_code = getattr(exc, "error_code", None) or "reconcile_failed"
                ref.sync_error_message = str(exc)[:512]
                ref.reconciliation_status = "failed"
                await db.flush()
                logger.warning(
                    "xero_reconcile_failed",
                    tenant_id=str(tenant_id),
                    ref_id=ref.id,
                    error=str(exc),
                )
        job.records_fetched = len(rows)
        job.records_updated = len(results)
        job.records_failed = failed
        job.records_persisted = len(results)
        await mark_job_completed(db, job)
        return {
            "job_id": job.id,
            "reconciled": len(results),
            "failed": failed,
            "items": results,
            "committed": False,
        }
    except (RuntimeError, XeroApiError) as exc:
        await mark_job_failed(
            db,
            job,
            error_code=getattr(exc, "error_code", None) or "reconcile_failed",
            error_message=str(exc),
        )
        raise
