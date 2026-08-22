"""Collections workflow for accounts receivable."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import Collection, CollectionStatus
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.schemas.collection import CollectionResponse, CollectionWorkspaceKpis
from app.services.master_data.customer_registry_service import resolve_customer_registry_id_for_invoice
from app.services.sales.sales_document_service import is_commercial_sales_invoice
from app.tenant_settings import tenant_today

_OPEN_STATUSES = (
    CollectionStatus.QUEUE,
    CollectionStatus.AWAITING,
)


def collection_to_response(row: Collection) -> CollectionResponse:
    tab = row.status.value
    return CollectionResponse(
        id=row.id,
        invoice_id=row.invoice_id,
        customer=row.customer,
        amount=float(row.amount),
        currency=row.currency,
        status=row.status.value,
        tab=tab,
        due_date=row.due_date,
        received_date=row.received_date,
        failure_reason=row.failure_reason,
    )


async def ensure_receivable_for_invoice(db: AsyncSession, invoice: Invoice) -> Collection | None:
    from app.services.invoice.invoice_evaluation_service import ROUTE_SALES

    if (invoice.route_target or "").strip() != ROUTE_SALES:
        return None
    if not is_commercial_sales_invoice(invoice):
        return None
    if invoice.status != InvoiceStatus.PROCESSED:
        return None
    if invoice.due_date is None or invoice.total is None or invoice.total <= 0:
        return None

    customer_registry_id = await resolve_customer_registry_id_for_invoice(
        db,
        invoice.tenant_id,
        customer_name=invoice.vendor,
        storage_slug=invoice.storage_vendor_slug,
    )

    existing = (
        await db.execute(
            select(Collection).where(
                Collection.tenant_id == invoice.tenant_id,
                Collection.invoice_id == invoice.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        if existing.amount != invoice.total:
            existing.amount = invoice.total
        if not existing.customer:
            existing.customer = invoice.vendor
        if not existing.due_date:
            existing.due_date = invoice.due_date
        if customer_registry_id is not None:
            existing.customer_registry_id = customer_registry_id
        return existing

    collection = Collection(
        tenant_id=invoice.tenant_id,
        invoice_id=invoice.id,
        customer_registry_id=customer_registry_id,
        customer=invoice.vendor,
        amount=invoice.total,
        currency=invoice.currency or "",
        due_date=invoice.due_date,
        status=CollectionStatus.QUEUE,
    )
    db.add(collection)
    await db.flush()
    return collection


async def list_collections(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    status: str | None = None,
    limit: int | None = None,
) -> list[CollectionResponse]:
    stmt = (
        select(Collection)
        .where(Collection.tenant_id == tenant_id)
        .order_by(Collection.created_at.desc())
    )
    if status:
        try:
            parsed = CollectionStatus(status)
        except ValueError as exc:
            raise ValueError(f"Invalid collection status: {status}") from exc
        stmt = stmt.where(Collection.status == parsed)
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [collection_to_response(row) for row in rows]


async def collection_workspace_kpis(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    tenant: Tenant | None = None,
) -> CollectionWorkspaceKpis:
    if tenant is None:
        tenant = await db.get(Tenant, tenant_id)
    today = tenant_today(tenant)
    due_soon_until = today + timedelta(days=7)

    status_rows = (
        await db.execute(
            select(Collection.status, func.count(Collection.id)).where(
                Collection.tenant_id == tenant_id
            ).group_by(Collection.status)
        )
    ).all()
    by_status: dict[str, int] = {}
    for status, count in status_rows:
        key = status.value if isinstance(status, CollectionStatus) else str(status)
        by_status[key] = int(count or 0)

    outstanding_rows = (
        await db.execute(
            select(
                Collection.currency,
                func.coalesce(func.sum(Collection.amount), 0),
            )
            .where(
                Collection.tenant_id == tenant_id,
                Collection.status.in_(_OPEN_STATUSES),
            )
            .group_by(Collection.currency)
        )
    ).all()
    outstanding_by_currency: dict[str, float] = {}
    for currency, amount in outstanding_rows:
        code = (currency or "").strip().upper()
        outstanding_by_currency[code] = outstanding_by_currency.get(code, 0.0) + float(amount or 0)

    overdue_count = (
        await db.execute(
            select(func.count(Collection.id)).where(
                Collection.tenant_id == tenant_id,
                Collection.status.in_(_OPEN_STATUSES),
                Collection.due_date.is_not(None),
                Collection.due_date < today,
            )
        )
    ).scalar() or 0
    due_soon_count = (
        await db.execute(
            select(func.count(Collection.id)).where(
                Collection.tenant_id == tenant_id,
                Collection.status.in_(_OPEN_STATUSES),
                Collection.due_date.is_not(None),
                Collection.due_date >= today,
                Collection.due_date <= due_soon_until,
            )
        )
    ).scalar() or 0

    queue_count = by_status.get(CollectionStatus.QUEUE.value, 0)
    awaiting_count = by_status.get(CollectionStatus.AWAITING.value, 0)
    return CollectionWorkspaceKpis(
        open_count=queue_count + awaiting_count,
        overdue_count=int(overdue_count),
        due_soon_count=int(due_soon_count),
        queue_count=queue_count,
        awaiting_count=awaiting_count,
        received_count=by_status.get(CollectionStatus.RECEIVED.value, 0),
        failed_count=by_status.get(CollectionStatus.FAILED.value, 0),
        outstanding_by_currency=outstanding_by_currency,
    )


async def mark_collection_received(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    collection_id: int,
    *,
    received_date: datetime | None = None,
) -> CollectionResponse:
    row = (
        await db.execute(
            select(Collection).where(
                Collection.id == collection_id,
                Collection.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError("Collection not found")

    row.status = CollectionStatus.RECEIVED
    row.received_date = received_date or datetime.now(timezone.utc)
    await db.flush()
    from app.services.payments.settlement_service import post_collection_settlement_journal

    await post_collection_settlement_journal(db, row)
    return collection_to_response(row)


async def collections_queue_count(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count(Collection.id)).where(
                Collection.tenant_id == tenant_id,
                Collection.status.in_(_OPEN_STATUSES),
            )
        )
    ).scalar() or 0
