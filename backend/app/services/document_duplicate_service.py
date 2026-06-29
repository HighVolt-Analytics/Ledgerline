"""Unified file-hash and business duplicate detection across capture channels."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.audit_service import log_event
from app.services.document_ref_service import assign_document_ref
from app.services.invoice_data import InvoiceData

DuplicateAction = Literal[
    "allow",
    "skip_in_progress",
    "skip_logged",
    "shadow_duplicate",
    "reingest_rejected",
]

IN_FLIGHT_STATUSES = frozenset(
    {
        InvoiceStatus.PENDING,
        InvoiceStatus.PARSING,
        InvoiceStatus.VALIDATING,
        InvoiceStatus.MAPPING,
        InvoiceStatus.JOURNALING,
        InvoiceStatus.RECONCILING,
        InvoiceStatus.EXCEPTION,
    }
)

VR02_IGNORE_STATUSES = frozenset(
    {
        InvoiceStatus.REJECTED,
        InvoiceStatus.DUPLICATE_SKIPPED,
    }
)


def normalize_invoice_number(value: str | None) -> str:
    """Strip punctuation/spaces for duplicate comparison."""
    if not value:
        return ""
    cleaned = re.sub(r"[^a-z0-9]", "", value.strip().lower())
    return cleaned


async def normalized_invoice_number_duplicate_exists(
    session: AsyncSession,
    data: InvoiceData,
    *,
    tenant_id: int,
    exclude_id: int | None = None,
) -> Invoice | None:
    target = normalize_invoice_number(data.invoice_no)
    if not target or not (data.vendor or "").strip():
        return None

    vendor_key = data.vendor.strip().lower()
    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            func.lower(Invoice.vendor) == vendor_key,
            Invoice.status.notin_(VR02_IGNORE_STATUSES),
        )
        .order_by(Invoice.created_at.desc())
    )
    if exclude_id is not None:
        stmt = stmt.where(Invoice.id != exclude_id)

    for row in (await session.execute(stmt)).scalars().all():
        if normalize_invoice_number(row.invoice_no) == target:
            return row
    return None


async def fuzzy_business_duplicate_exists(
    session: AsyncSession,
    data: InvoiceData,
    *,
    tenant_id: int,
    exclude_id: int | None = None,
    amount_pct: Decimal = Decimal("0.005"),
    date_window_days: int = 7,
) -> Invoice | None:
    """Same vendor, similar amount (±pct), invoice date within ±days."""
    if not (data.vendor or "").strip() or data.total is None or data.invoice_date is None:
        return None

    vendor_key = data.vendor.strip().lower()
    amount = data.total
    low = amount * (Decimal("1") - amount_pct)
    high = amount * (Decimal("1") + amount_pct)
    start = data.invoice_date - timedelta(days=date_window_days)
    end = data.invoice_date + timedelta(days=date_window_days)

    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            func.lower(Invoice.vendor) == vendor_key,
            Invoice.total.is_not(None),
            Invoice.total >= low,
            Invoice.total <= high,
            Invoice.invoice_date.is_not(None),
            Invoice.invoice_date >= start,
            Invoice.invoice_date <= end,
            Invoice.status.notin_(VR02_IGNORE_STATUSES),
        )
        .order_by(Invoice.created_at.desc())
    )
    if exclude_id is not None:
        stmt = stmt.where(Invoice.id != exclude_id)

    for row in (await session.execute(stmt)).scalars().all():
        if (row.invoice_no or "").strip().lower() == (data.invoice_no or "").strip().lower():
            continue
        return row
    return None


@dataclass(frozen=True)
class FileDuplicateDecision:
    action: DuplicateAction
    existing: Invoice | None = None


async def find_invoice_by_file_hash(
    session: AsyncSession,
    file_hash: str,
    *,
    tenant_id: int,
) -> Invoice | None:
    stmt = select(Invoice).where(
        Invoice.file_hash == file_hash,
        Invoice.tenant_id == tenant_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def evaluate_file_hash_duplicate(existing: Invoice | None) -> FileDuplicateDecision:
    """Decide how ingest should handle a file that matches an existing invoice hash."""
    if existing is None:
        return FileDuplicateDecision(action="allow")

    if existing.status == InvoiceStatus.REJECTED:
        return FileDuplicateDecision(action="reingest_rejected", existing=existing)

    if existing.status in IN_FLIGHT_STATUSES:
        return FileDuplicateDecision(action="skip_in_progress", existing=existing)

    if existing.status == InvoiceStatus.PROCESSED:
        return FileDuplicateDecision(action="shadow_duplicate", existing=existing)

    if existing.status == InvoiceStatus.DUPLICATE_SKIPPED:
        return FileDuplicateDecision(action="skip_logged", existing=existing)

    return FileDuplicateDecision(action="skip_logged", existing=existing)


async def log_duplicate_in_progress(
    session: AsyncSession,
    existing: Invoice,
    *,
    detail: dict[str, Any],
) -> None:
    await log_event(
        session,
        "duplicate_in_progress",
        invoice_id=existing.id,
        detail=detail,
    )


async def log_duplicate_skipped(
    session: AsyncSession,
    invoice_id: int,
    *,
    detail: dict[str, Any],
) -> None:
    await log_event(
        session,
        "duplicate_skipped",
        invoice_id=invoice_id,
        detail=detail,
    )


async def create_duplicate_shadow_invoice(
    session: AsyncSession,
    *,
    tenant_id: int,
    original: Invoice,
    connected_mailbox_id: int | None = None,
    whatsapp_connection_id: int | None = None,
    viber_connection_id: int | None = None,
    email_sender: str | None = None,
    email_subject: str | None = None,
    email_attachment_name: str | None = None,
    email_message_id: str | None = None,
    capture_source: str | None = None,
    file_hash: str,
    extra_detail: dict[str, Any] | None = None,
) -> Invoice:
    """
    Record a duplicate submission without changing the original processed invoice.

    Shadow rows omit file_hash so the unique (tenant_id, file_hash) constraint still
  protects the canonical stored document on the original row.
    """
    shadow = Invoice(
        tenant_id=tenant_id,
        connected_mailbox_id=connected_mailbox_id,
        whatsapp_connection_id=whatsapp_connection_id,
        viber_connection_id=viber_connection_id,
        status=InvoiceStatus.DUPLICATE_SKIPPED,
        file_hash=None,
        vendor=original.vendor,
        invoice_no=original.invoice_no,
        total=original.total,
        currency=original.currency,
        email_sender=email_sender,
        email_subject=email_subject,
        email_attachment_name=email_attachment_name,
        email_message_id=email_message_id,
        capture_source=capture_source,
        route_target=original.route_target,
        storage_vendor_slug=original.storage_vendor_slug,
    )
    session.add(shadow)
    await session.flush()
    await assign_document_ref(session, shadow)

    detail: dict[str, Any] = {
        "original_invoice_id": original.id,
        "file_hash": file_hash,
        "preserved_original_status": original.status.value,
    }
    if extra_detail:
        detail.update(extra_detail)

    await log_duplicate_skipped(session, shadow.id, detail=detail)
    return shadow


async def invoice_number_duplicate_exists(
    session: AsyncSession,
    data: InvoiceData,
    *,
    tenant_id: int,
    exclude_id: int | None = None,
) -> Invoice | None:
    """Return an existing invoice that blocks VR02, if any."""
    if not (data.invoice_no or "").strip():
        return None
    if not (data.vendor or "").strip():
        return None

    vendor_key = data.vendor.strip().lower()
    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            func.lower(Invoice.invoice_no) == data.invoice_no.strip().lower(),
            func.lower(Invoice.vendor) == vendor_key,
            Invoice.status.notin_(VR02_IGNORE_STATUSES),
        )
        .order_by(Invoice.created_at.desc())
    )
    if exclude_id is not None:
        stmt = stmt.where(Invoice.id != exclude_id)

    return (await session.execute(stmt)).scalars().first()
