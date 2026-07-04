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
from app.services.audit.audit_service import log_event
from app.services.dossier.document_ref_service import assign_document_ref
from app.services.invoice.invoice_data import InvoiceData

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
    }
)

_DUPLICATE_SHADOW_STATUSES = frozenset(
    {
        InvoiceStatus.PROCESSED,
        InvoiceStatus.VALIDATING,
        InvoiceStatus.MAPPING,
        InvoiceStatus.JOURNALING,
        InvoiceStatus.RECONCILING,
        InvoiceStatus.EXCEPTION,
    }
)

_DUPLICATE_LOOKUP_IGNORE_STATUSES = frozenset(
    {
        InvoiceStatus.PENDING,
        InvoiceStatus.PARSING,
        InvoiceStatus.DUPLICATE_SKIPPED,
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


async def find_invoice_by_source_file_hash(
    session: AsyncSession,
    source_file_hash: str,
    *,
    tenant_id: int,
) -> Invoice | None:
    """Match a prior bundle segment row created from the same parent PDF hash."""
    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.status != InvoiceStatus.DUPLICATE_SKIPPED,
            Invoice.status.notin_(_DUPLICATE_LOOKUP_IGNORE_STATUSES),
            Invoice.extracted_fields.isnot(None),
            Invoice.extracted_fields["source_file_hash"].as_string() == source_file_hash,
        )
        .order_by(Invoice.created_at.asc())
    )
    return (await session.execute(stmt)).scalars().first()


async def find_invoice_by_content_fingerprint(
    session: AsyncSession,
    content_fingerprint: str,
    *,
    tenant_id: int,
) -> Invoice | None:
    stmt = (
        select(Invoice)
        .where(
            Invoice.content_fingerprint == content_fingerprint,
            Invoice.tenant_id == tenant_id,
            Invoice.status.notin_(_DUPLICATE_LOOKUP_IGNORE_STATUSES),
        )
        .order_by(Invoice.created_at.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def find_invoice_by_business_fingerprint(
    session: AsyncSession,
    business_fingerprint: str,
    *,
    tenant_id: int,
) -> Invoice | None:
    stmt = (
        select(Invoice)
        .where(
            Invoice.business_fingerprint == business_fingerprint,
            Invoice.tenant_id == tenant_id,
            Invoice.status.notin_(_DUPLICATE_LOOKUP_IGNORE_STATUSES),
        )
        .order_by(Invoice.created_at.desc())
    )
    return (await session.execute(stmt)).scalars().first()


_LINKING_REFERENCE_KEYS = frozenset({"po_reference", "so_reference"})
_REGISTER_TYPE_KEYS = frozenset({"sales_document_type", "purchase_document_type"})
_MONEY_KEYS = frozenset({"total", "subtotal"})


def _is_reference_key(key: str) -> bool:
    if key in {"invoice_no", "po_reference", "so_reference"}:
        return True
    return key.endswith("_no") or key.endswith("_reference") or key.endswith("_ref")


def _is_document_number_key(key: str) -> bool:
    if key == "invoice_no":
        return True
    if key in _LINKING_REFERENCE_KEYS:
        return False
    return key.endswith("_no")


def _register_types_differ(left: dict[str, str], right: dict[str, str]) -> bool:
    for key in _REGISTER_TYPE_KEYS:
        left_val = (left.get(key) or "").strip().lower()
        right_val = (right.get(key) or "").strip().lower()
        if left_val and right_val and left_val != right_val:
            return True
    return False


def _invoice_identity_snapshot(invoice: Invoice) -> dict[str, str]:
    from app.services.extraction.extraction_field_values import extracted_fields_from_invoice

    fields: dict[str, str] = {}
    for key in ("vendor", "invoice_no", "po_reference", "so_reference"):
        value = getattr(invoice, key, None)
        if isinstance(value, str) and value.strip():
            fields[key] = value.strip()
    if invoice.total is not None:
        fields["total"] = str(invoice.total)
    sales_type = (invoice.sales_document_type or "").strip().lower()
    if sales_type:
        fields["sales_document_type"] = sales_type
    purchase_type = (invoice.purchase_document_type or "").strip().lower()
    if purchase_type:
        fields["purchase_document_type"] = purchase_type
    fields.update(extracted_fields_from_invoice(invoice))
    return fields


def _identity_fields_overlap(left: dict[str, str], right: dict[str, str]) -> bool:
    if not left or not right:
        return False
    if _register_types_differ(left, right):
        return False
    shared_keys = set(left) & set(right)
    ref_keys = {k for k in shared_keys if _is_reference_key(k)}
    if not ref_keys:
        return False
    matched_refs = {k for k in ref_keys if left[k] == right[k]}
    if not matched_refs:
        return False
    left_vendor = left.get("vendor")
    right_vendor = right.get("vendor")
    if left_vendor and right_vendor and left_vendor != right_vendor:
        return False
    if any(_is_document_number_key(k) for k in matched_refs):
        return True
    if any(k in shared_keys and left[k] == right[k] for k in _MONEY_KEYS):
        return True
    return False


async def identity_overlap_duplicate_exists(
    session: AsyncSession,
    identity_fields: dict[str, str],
    *,
    tenant_id: int,
    exclude_id: int | None = None,
) -> Invoice | None:
    from app.services.extraction.document_identity_service import normalize_identity_fields

    target = normalize_identity_fields(identity_fields)
    if not target:
        return None

    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.status.notin_(VR02_IGNORE_STATUSES),
            Invoice.status.notin_(_DUPLICATE_LOOKUP_IGNORE_STATUSES),
        )
        .order_by(Invoice.created_at.desc())
    )
    if exclude_id is not None:
        stmt = stmt.where(Invoice.id != exclude_id)

    for row in (await session.execute(stmt)).scalars().all():
        candidate = normalize_identity_fields(_invoice_identity_snapshot(row))
        if _identity_fields_overlap(target, candidate):
            return row
    return None


async def identity_duplicate_exists(
    session: AsyncSession,
    data: InvoiceData,
    *,
    tenant_id: int,
    exclude_id: int | None = None,
    custom_field_keys: list[str] | None = None,
) -> Invoice | None:
    from app.services.extraction.document_identity_service import (
        extract_identity_fields,
        is_identity_field_key,
    )
    from app.services.extraction.extraction_field_values import extracted_fields_from_parsed

    fields: dict[str, str] = {}
    for key in ("vendor", "invoice_no", "po_reference", "so_reference"):
        value = getattr(data, key, None)
        if isinstance(value, str) and value.strip():
            fields[key] = value.strip()
    if data.total is not None:
        fields["total"] = str(data.total)

    allowed = set(custom_field_keys or [])
    for key, value in extracted_fields_from_parsed(data).items():
        if (not allowed or key in allowed or is_identity_field_key(key)) and value.strip():
            fields[key] = value.strip()

    if data.document_text:
        harvested = extract_identity_fields(
            data.document_text,
            custom_field_keys=list(allowed) if allowed else None,
        )
        fields.update(harvested)

    overlap = await identity_overlap_duplicate_exists(
        session,
        fields,
        tenant_id=tenant_id,
        exclude_id=exclude_id,
    )
    if overlap is not None:
        return overlap

    duplicate = await invoice_number_duplicate_exists(
        session,
        data,
        tenant_id=tenant_id,
        exclude_id=exclude_id,
    )
    if duplicate is not None:
        return duplicate

    return await normalized_invoice_number_duplicate_exists(
        session,
        data,
        tenant_id=tenant_id,
        exclude_id=exclude_id,
    )


async def find_existing_ingest_duplicate(
    session: AsyncSession,
    *,
    tenant_id: int,
    file_hash: str,
    content_fingerprint: str | None = None,
    business_fingerprint: str | None = None,
    identity_fields: dict[str, str] | None = None,
) -> Invoice | None:
    """Match by file hash, bundle source hash, business fingerprint, content fingerprint, or identity overlap."""
    existing = await find_invoice_by_file_hash(session, file_hash, tenant_id=tenant_id)
    if existing is not None:
        return existing
    existing = await find_invoice_by_source_file_hash(session, file_hash, tenant_id=tenant_id)
    if existing is not None:
        return existing
    if business_fingerprint:
        existing = await find_invoice_by_business_fingerprint(
            session,
            business_fingerprint,
            tenant_id=tenant_id,
        )
        if existing is not None:
            return existing
    if content_fingerprint:
        existing = await find_invoice_by_content_fingerprint(
            session,
            content_fingerprint,
            tenant_id=tenant_id,
        )
        if existing is not None:
            return existing
    if identity_fields:
        return await identity_overlap_duplicate_exists(
            session,
            identity_fields,
            tenant_id=tenant_id,
        )
    return None


def _invoice_status(invoice: Invoice) -> InvoiceStatus:
    status = invoice.status
    if isinstance(status, InvoiceStatus):
        return status
    return InvoiceStatus(str(status))


def evaluate_file_hash_duplicate(existing: Invoice | None) -> FileDuplicateDecision:
    """Decide how ingest should handle a file that matches an existing invoice hash."""
    if existing is None:
        return FileDuplicateDecision(action="allow")

    status = _invoice_status(existing)

    if status == InvoiceStatus.REJECTED:
        return FileDuplicateDecision(action="reingest_rejected", existing=existing)

    if status in IN_FLIGHT_STATUSES:
        return FileDuplicateDecision(action="skip_in_progress", existing=existing)

    if status in _DUPLICATE_SHADOW_STATUSES:
        return FileDuplicateDecision(action="shadow_duplicate", existing=existing)

    if status == InvoiceStatus.DUPLICATE_SKIPPED:
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


@dataclass(frozen=True)
class IngestDuplicateOutcome:
    """Result of handling a duplicate during ingest."""

    handled: bool
    invoice_id: int | None = None
    existing: Invoice | None = None
    action: DuplicateAction | None = None


async def resolve_ingest_duplicate(
    session: AsyncSession,
    *,
    tenant_id: int,
    existing: Invoice,
    file_hash: str,
    content_fingerprint: str | None = None,
    business_fingerprint: str | None = None,
    capture_source: str | None = None,
    connected_mailbox_id: int | None = None,
    whatsapp_connection_id: int | None = None,
    viber_connection_id: int | None = None,
    email_sender: str | None = None,
    email_subject: str | None = None,
    email_attachment_name: str | None = None,
    email_message_id: str | None = None,
    extra_detail: dict[str, Any] | None = None,
) -> IngestDuplicateOutcome:
    """Apply the standard duplicate decision matrix for an ingest channel."""
    decision = evaluate_file_hash_duplicate(existing)
    detail: dict[str, Any] = {
        "filename": email_attachment_name,
        "source": capture_source or "upload",
        **(extra_detail or {}),
    }
    if content_fingerprint:
        detail["content_fingerprint"] = content_fingerprint
    if business_fingerprint:
        detail["business_fingerprint"] = business_fingerprint

    if decision.action == "allow":
        return IngestDuplicateOutcome(handled=False, existing=existing, action="allow")

    if decision.action == "skip_in_progress":
        if email_message_id:
            existing.email_message_id = email_message_id
        await log_duplicate_in_progress(session, existing, detail=detail)
        return IngestDuplicateOutcome(
            handled=True,
            existing=existing,
            action=decision.action,
        )

    if decision.action == "skip_logged":
        if email_message_id:
            existing.email_message_id = email_message_id
        await log_event(
            session,
            "duplicate_skipped",
            invoice_id=existing.id,
            detail={**detail, "note": "repeat submission ignored"},
        )
        return IngestDuplicateOutcome(
            handled=True,
            existing=existing,
            action=decision.action,
        )

    if decision.action == "shadow_duplicate":
        shadow = await create_duplicate_shadow_invoice(
            session,
            tenant_id=tenant_id,
            original=existing,
            connected_mailbox_id=connected_mailbox_id,
            whatsapp_connection_id=whatsapp_connection_id,
            viber_connection_id=viber_connection_id,
            email_sender=email_sender,
            email_subject=email_subject,
            email_attachment_name=email_attachment_name,
            email_message_id=email_message_id,
            capture_source=capture_source,
            file_hash=file_hash,
            extra_detail=detail,
        )
        return IngestDuplicateOutcome(
            handled=True,
            invoice_id=shadow.id,
            existing=existing,
            action=decision.action,
        )

    if decision.action == "reingest_rejected":
        from app.services.invoice.pipeline import reset_invoice_for_reprocess

        if email_sender is not None:
            existing.email_sender = email_sender
        if email_subject is not None:
            existing.email_subject = email_subject
        if email_attachment_name is not None:
            existing.email_attachment_name = email_attachment_name
        if email_message_id is not None:
            existing.email_message_id = email_message_id
        await reset_invoice_for_reprocess(session, existing)
        await log_event(
            session,
            "duplicate_reingest_rejected",
            invoice_id=existing.id,
            detail=detail,
        )
        return IngestDuplicateOutcome(
            handled=True,
            invoice_id=existing.id,
            existing=existing,
            action=decision.action,
        )

    return IngestDuplicateOutcome(
        handled=True,
        existing=existing,
        action=decision.action,
    )


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
