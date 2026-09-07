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
from app.services.dossier.document_ref_service import (
    assign_document_ref,
    original_document_audit_fields,
)
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

# Ingest duplicate checks must see in-flight rows so a batch cannot insert the same
# content_fingerprint twice before the first row commits (DB unique constraint).
_INGEST_FINGERPRINT_LOOKUP_IGNORE_STATUSES = frozenset(
    {
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
    """Strip punctuation/spaces for duplicate comparison (leading zeros collapsed)."""
    from app.services.extraction.invoice_no_sanitizer import normalize_invoice_number_token

    return normalize_invoice_number_token(value)


def _invoice_data_dup_tokens(data: InvoiceData) -> set[str]:
    from app.services.extraction.invoice_no_sanitizer import (
        INVOICE_NO_SECONDARY_KEY,
        invoice_no_dup_tokens_from_values,
    )

    secondary = None
    extracted = data.extracted_fields or {}
    if isinstance(extracted, dict):
        secondary = extracted.get(INVOICE_NO_SECONDARY_KEY)
    return invoice_no_dup_tokens_from_values(data.invoice_no, secondary)


def _invoice_row_dup_tokens(row: Invoice) -> set[str]:
    from app.services.extraction.invoice_no_sanitizer import (
        INVOICE_NO_SECONDARY_KEY,
        invoice_no_dup_tokens_from_values,
    )

    secondary = None
    extracted = row.extracted_fields or {}
    if isinstance(extracted, dict):
        secondary = extracted.get(INVOICE_NO_SECONDARY_KEY)
    return invoice_no_dup_tokens_from_values(row.invoice_no, secondary)


async def normalized_invoice_number_duplicate_exists(
    session: AsyncSession,
    data: InvoiceData,
    *,
    tenant_id: int,
    exclude_id: int | None = None,
    document_role: str | None = None,
) -> Invoice | None:
    targets = _invoice_data_dup_tokens(data)
    if not targets or not (data.vendor or "").strip():
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
        if document_roles_conflict(document_role, document_role_from_invoice(row)):
            continue
        if _invoice_row_dup_tokens(row) & targets:
            return row
    return None


async def fuzzy_business_duplicate_exists(
    session: AsyncSession,
    data: InvoiceData,
    *,
    tenant_id: int,
    exclude_id: int | None = None,
    amount_pct: Decimal | None = None,
    date_window_days: int | None = None,
) -> Invoice | None:
    """Same vendor, similar amount (±pct), invoice date within ±days."""
    from app.config import get_settings

    settings = get_settings()
    if amount_pct is None:
        amount_pct = Decimal(str(settings.fuzzy_amount_tolerance_pct))
    if date_window_days is None:
        date_window_days = int(settings.fuzzy_date_window_days)

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


def fuzzy_match_confidence(
    data: InvoiceData,
    other: Invoice,
    *,
    amount_pct: Decimal | None = None,
    date_window_days: int | None = None,
) -> float:
    """Weighted 0–1 score from amount + date closeness (Layer 4)."""
    from app.config import get_settings

    settings = get_settings()
    if amount_pct is None:
        amount_pct = Decimal(str(settings.fuzzy_amount_tolerance_pct))
    if date_window_days is None:
        date_window_days = int(settings.fuzzy_date_window_days)

    amount_score = 0.0
    if data.total is not None and other.total is not None and amount_pct > 0:
        base = abs(data.total) if data.total != 0 else Decimal("0.01")
        rel = abs(data.total - other.total) / base
        amount_score = max(0.0, float(1 - (rel / amount_pct)))

    date_score = 0.0
    if data.invoice_date is not None and other.invoice_date is not None and date_window_days > 0:
        days = abs((data.invoice_date - other.invoice_date).days)
        date_score = max(0.0, 1.0 - (days / float(date_window_days)))

    return round(0.5 * amount_score + 0.5 * date_score, 4)


DuplicateMatchKind = Literal["identity_overlap", "exact", "normalized", "fuzzy"]


@dataclass(frozen=True)
class BusinessDuplicateMatch:
    invoice: Invoice
    kind: DuplicateMatchKind
    confidence_score: float | None = None


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


async def find_invoice_by_content_fingerprint_for_ingest(
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
            Invoice.status.notin_(_INGEST_FINGERPRINT_LOOKUP_IGNORE_STATUSES),
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


async def find_invoice_by_business_fingerprint_for_ingest(
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
            Invoice.status.notin_(_INGEST_FINGERPRINT_LOOKUP_IGNORE_STATUSES),
        )
        .order_by(Invoice.created_at.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def find_invoices_by_business_fingerprint_for_ingest(
    session: AsyncSession,
    business_fingerprint: str,
    *,
    tenant_id: int,
    limit: int = 20,
) -> list[Invoice]:
    """Newest-first candidates sharing a business fingerprint (cross-type filter applied by caller)."""
    stmt = (
        select(Invoice)
        .where(
            Invoice.business_fingerprint == business_fingerprint,
            Invoice.tenant_id == tenant_id,
            Invoice.status.notin_(_INGEST_FINGERPRINT_LOOKUP_IGNORE_STATUSES),
        )
        .order_by(Invoice.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


_LINKING_REFERENCE_KEYS = frozenset({"po_reference", "so_reference"})
_REGISTER_TYPE_KEYS = frozenset({"sales_document_type", "purchase_document_type", "document_role"})
_MONEY_KEYS = frozenset({"total", "subtotal"})
# Mirror document_identity_service — logistics companions share invoice_no as a cross-ref.
_LOGISTICS_ROLES = frozenset(
    {"packing_list", "transport_doc", "grn", "certificate_of_origin"}
)
_LOGISTICS_PRIMARY_KEYS = frozenset({"bol_no", "freight_order_no", "tracking_no", "hawb_no"})

_PURCHASE_TYPE_TO_ROLE = {
    "invoice": "invoice",
    "po": "purchase_order",
    "grn": "grn",
}


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


def document_role_from_invoice(invoice: Invoice) -> str | None:
    """Best-effort document role for cross-type dedup (invoice vs packing list vs DN)."""
    from app.services.extraction.document_heading_utils import (
        document_role_from_heading,
        infer_page_document_kind,
    )

    purchase = (invoice.purchase_document_type or "").strip().lower()
    mapped = _PURCHASE_TYPE_TO_ROLE.get(purchase)
    if mapped:
        return mapped
    heading = (invoice.document_heading or "").strip()
    if heading:
        return document_role_from_heading(infer_page_document_kind(heading))
    extracted = invoice.extracted_fields if isinstance(invoice.extracted_fields, dict) else {}
    role = str(extracted.get("document_role") or "").strip().lower()
    return role or None


def document_roles_conflict(left: str | None, right: str | None) -> bool:
    """True when both roles are known and different — never treat as the same instrument."""
    left_role = (left or "").strip().lower()
    right_role = (right or "").strip().lower()
    if not left_role or not right_role:
        return False
    return left_role != right_role


def _register_types_differ(left: dict[str, str], right: dict[str, str]) -> bool:
    for key in _REGISTER_TYPE_KEYS:
        left_val = (left.get(key) or "").strip().lower()
        right_val = (right.get(key) or "").strip().lower()
        if left_val and right_val and left_val != right_val:
            return True
    return False


def _field_role(fields: dict[str, str]) -> str | None:
    return (fields.get("document_role") or "").strip().lower() or None


def _logistics_primaries_conflict(left: dict[str, str], right: dict[str, str]) -> bool:
    """True when both sides expose different BOL/HAWB/tracking ids — distinct instruments."""
    for key in _LOGISTICS_PRIMARY_KEYS:
        left_val = (left.get(key) or "").strip()
        right_val = (right.get(key) or "").strip()
        if left_val and right_val and left_val != right_val:
            return True
    return False


def _matched_refs_for_overlap(
    left: dict[str, str],
    right: dict[str, str],
    matched_refs: set[str],
) -> set[str]:
    """
    Drop weak cross-refs that must not hard-block.

    Packing lists / transport docs / GRNs often reprint the commercial invoice number.
    That shared invoice_no is a shipment link, not proof the PDF is the same instrument.
    """
    left_role = _field_role(left)
    right_role = _field_role(right)
    either_logistics = left_role in _LOGISTICS_ROLES or right_role in _LOGISTICS_ROLES
    if either_logistics:
        return {key for key in matched_refs if key != "invoice_no"}
    return matched_refs


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
    role = document_role_from_invoice(invoice)
    if role:
        fields["document_role"] = role
    fields.update(extracted_fields_from_invoice(invoice))
    # Prefer derived role over a stale extracted_fields copy.
    if role:
        fields["document_role"] = role
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
    matched_refs = _matched_refs_for_overlap(left, right, matched_refs)
    if not matched_refs:
        return False
    left_vendor = left.get("vendor")
    right_vendor = right.get("vendor")
    if left_vendor and right_vendor and left_vendor != right_vendor:
        return False
    # Distinct logistics ids always win over a shared commercial invoice number.
    if _logistics_primaries_conflict(left, right):
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


def _document_role_from_invoice_data(data: InvoiceData) -> str | None:
    """Best-effort role for VR02 so packing lists don't collide with invoices on invoice_no."""
    from app.services.extraction.document_heading_utils import (
        document_role_from_heading,
        infer_page_document_kind,
    )

    extracted = data.extracted_fields if isinstance(data.extracted_fields, dict) else {}
    role = str(extracted.get("document_role") or "").strip().lower()
    if role:
        return role
    heading = (data.document_heading or "").strip()
    if heading:
        inferred = document_role_from_heading(infer_page_document_kind(heading))
        if inferred:
            return inferred
    text = (data.document_text or "").strip()
    if text:
        # First ~2k chars usually contain the title block.
        return document_role_from_heading(infer_page_document_kind(text[:2000]))
    return None


async def identity_duplicate_exists(
    session: AsyncSession,
    data: InvoiceData,
    *,
    tenant_id: int,
    exclude_id: int | None = None,
    custom_field_keys: list[str] | None = None,
) -> BusinessDuplicateMatch | None:
    from app.config import get_settings
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

    role = _document_role_from_invoice_data(data)
    if role:
        fields["document_role"] = role

    overlap = await identity_overlap_duplicate_exists(
        session,
        fields,
        tenant_id=tenant_id,
        exclude_id=exclude_id,
    )
    if overlap is not None:
        return BusinessDuplicateMatch(invoice=overlap, kind="identity_overlap")

    # Exact / normalized invoice_no checks are commercial-instrument matches.
    # Skip them for logistics roles — companions reprint the invoice number.
    if role not in _LOGISTICS_ROLES:
        duplicate = await invoice_number_duplicate_exists(
            session,
            data,
            tenant_id=tenant_id,
            exclude_id=exclude_id,
            document_role=role,
        )
        if duplicate is not None:
            return BusinessDuplicateMatch(invoice=duplicate, kind="exact")

        normalized = await normalized_invoice_number_duplicate_exists(
            session,
            data,
            tenant_id=tenant_id,
            exclude_id=exclude_id,
            document_role=role,
        )
        if normalized is not None:
            return BusinessDuplicateMatch(invoice=normalized, kind="normalized")

    if get_settings().fuzzy_duplicate_check_enabled:
        fuzzy = await fuzzy_business_duplicate_exists(
            session,
            data,
            tenant_id=tenant_id,
            exclude_id=exclude_id,
        )
        if fuzzy is not None:
            return BusinessDuplicateMatch(
                invoice=fuzzy,
                kind="fuzzy",
                confidence_score=fuzzy_match_confidence(data, fuzzy),
            )
    return None


MatchKind = Literal[
    "file_hash",
    "source_file_hash",
    "business_fingerprint",
    "content_fingerprint",
    "identity_overlap",
    "page_fingerprint",
    "filename_combo",
]

ConfidenceTier = Literal["T1", "T2", "T3", "T4"]


@dataclass(frozen=True)
class IngestDuplicateMatch:
    """A found duplicate with confidence tier metadata for canonical intake."""

    invoice: Invoice
    match_kind: MatchKind
    confidence_tier: ConfidenceTier


def classify_match_tier(match_kind: MatchKind) -> ConfidenceTier:
    if match_kind in {"file_hash", "source_file_hash"}:
        return "T1"
    if match_kind in {"business_fingerprint", "content_fingerprint", "identity_overlap", "filename_combo"}:
        return "T2"
    if match_kind == "page_fingerprint":
        return "T3"
    return "T4"


def signals_are_sparse(
    *,
    content_fingerprint: str | None,
    business_fingerprint: str | None,
    identity_fields: dict[str, str] | None,
    page_fingerprints: list[str] | None,
) -> bool:
    """True when ≥3 of 4 signal families are unavailable (T4 allow-weak path)."""
    families_present = 0
    # file_hash is always present at ingest; count the other three + identity as fourth family
    if content_fingerprint:
        families_present += 1
    if business_fingerprint:
        families_present += 1
    if identity_fields and any((v or "").strip() for v in identity_fields.values()):
        families_present += 1
    if page_fingerprints:
        families_present += 1
    # 4 families beyond raw bytes: content, business, identity, page — sparse if ≤1 present
    return families_present <= 1


async def refresh_duplicate_review_after_ocr(
    session: AsyncSession,
    invoice: Invoice,
    *,
    ocr_text: str | None,
    custom_field_keys: list[str] | None = None,
) -> bool:
    """
    After pipeline OCR, backfill fingerprints and clear T4 when signals are no longer sparse.

    Used when ingest skipped OCR (images) or DI returned thin text that later OCR recovers.
    Does not invent fingerprints from empty OCR. Skips unique fingerprint writes that would
    collide with another invoice (those stay review-suggested as true possible duplicates).
    """
    if not getattr(invoice, "duplicate_review_suggested", False):
        return False
    text = (ocr_text or "").strip()
    if not text:
        return False

    from app.services.extraction.document_heading_utils import infer_document_role_from_pages
    from app.services.extraction.document_identity_service import (
        compute_business_fingerprint,
        extract_identity_fields_from_pages,
    )
    from app.services.extraction.pdf_content_fingerprint import (
        compute_pdf_content_fingerprint_from_pages,
    )
    from app.services.extraction.pdf_page_text_service import PdfPageText
    from app.services.ingest.page_fingerprint_service import (
        collect_page_fingerprints,
        persist_invoice_page_fingerprints,
    )

    pages = [PdfPageText(page_index=0, text=text)]
    content_fp = compute_pdf_content_fingerprint_from_pages(pages)
    identity_fields = extract_identity_fields_from_pages(
        pages,
        custom_field_keys=custom_field_keys,
    )
    inferred_role = infer_document_role_from_pages(pages)
    if inferred_role:
        identity_fields = {**identity_fields, "document_role": inferred_role}
    business_fp = compute_business_fingerprint(identity_fields)
    page_pairs = collect_page_fingerprints(pages)
    page_fps = [fp for _, fp in page_pairs]

    if signals_are_sparse(
        content_fingerprint=content_fp or invoice.content_fingerprint,
        business_fingerprint=business_fp or invoice.business_fingerprint,
        identity_fields=identity_fields or None,
        page_fingerprints=page_fps or None,
    ):
        return False

    tenant_id = invoice.tenant_id
    content_conflict = False
    business_conflict = False

    if content_fp and not invoice.content_fingerprint:
        existing = await find_invoice_by_content_fingerprint_for_ingest(
            session,
            content_fp,
            tenant_id=tenant_id,  # type: ignore[arg-type]
        )
        if existing is not None and existing.id != invoice.id:
            content_conflict = True
        else:
            invoice.content_fingerprint = content_fp

    if business_fp and not invoice.business_fingerprint:
        existing_biz = await find_invoice_by_business_fingerprint_for_ingest(
            session,
            business_fp,
            tenant_id=tenant_id,  # type: ignore[arg-type]
        )
        if existing_biz is not None and existing_biz.id != invoice.id:
            business_conflict = True
        else:
            invoice.business_fingerprint = business_fp

    if page_pairs:
        await persist_invoice_page_fingerprints(
            session,
            tenant_id=tenant_id,  # type: ignore[arg-type]
            invoice_id=invoice.id,
            pages=pages,
        )

    if content_conflict or business_conflict:
        # Strong OCR text matches another row — keep review flag (real duplicate risk).
        await log_event(
            session,
            "duplicate_review_fingerprint_conflict",
            invoice_id=invoice.id,
            detail={
                "content_conflict": content_conflict,
                "business_conflict": business_conflict,
                "content_fingerprint": content_fp,
                "business_fingerprint": business_fp,
            },
        )
        return False

    invoice.duplicate_review_suggested = False
    await log_event(
        session,
        "duplicate_review_cleared",
        invoice_id=invoice.id,
        detail={
            "reason": "ocr_signals_sufficient",
            "content_fingerprint": invoice.content_fingerprint,
            "business_fingerprint": invoice.business_fingerprint,
            "page_fingerprint_count": len(page_pairs),
            "identity_field_count": len(identity_fields or {}),
        },
    )
    return True


async def find_existing_ingest_duplicate_match(
    session: AsyncSession,
    *,
    tenant_id: int,
    file_hash: str,
    content_fingerprint: str | None = None,
    business_fingerprint: str | None = None,
    identity_fields: dict[str, str] | None = None,
    page_fingerprints: list[str] | None = None,
    check_page_fingerprints: bool = False,
    normalized_filename: str | None = None,
    document_role: str | None = None,
) -> IngestDuplicateMatch | None:
    """
    Tiered ingest duplicate lookup.

    T1: file / source hash.
    T2: business FP, content FP, identity overlap (filename alone never matches).
    T3: page fingerprints — only when ``check_page_fingerprints`` is True (last resort).

    ``document_role`` (or identity_fields['document_role']) prevents shipment companions
    that share invoice/PO numbers (invoice + packing list + DN) from collapsing.
    """
    incoming_role = (document_role or "").strip().lower() or None
    if not incoming_role and identity_fields:
        incoming_role = (identity_fields.get("document_role") or "").strip().lower() or None

    existing = await find_invoice_by_file_hash(session, file_hash, tenant_id=tenant_id)
    if existing is not None:
        return IngestDuplicateMatch(existing, "file_hash", "T1")

    existing = await find_invoice_by_source_file_hash(session, file_hash, tenant_id=tenant_id)
    if existing is not None:
        return IngestDuplicateMatch(existing, "source_file_hash", "T1")

    if business_fingerprint:
        for candidate in await find_invoices_by_business_fingerprint_for_ingest(
            session,
            business_fingerprint,
            tenant_id=tenant_id,
        ):
            if document_roles_conflict(incoming_role, document_role_from_invoice(candidate)):
                continue
            return IngestDuplicateMatch(candidate, "business_fingerprint", "T2")

    if content_fingerprint:
        # Content FP is page-text identity — always match. Role must NOT bypass this:
        # uq_invoice_tenant_content_fingerprint is absolute; skipping here causes 500s.
        existing = await find_invoice_by_content_fingerprint_for_ingest(
            session,
            content_fingerprint,
            tenant_id=tenant_id,
        )
        if existing is not None:
            return IngestDuplicateMatch(existing, "content_fingerprint", "T2")

    if identity_fields:
        existing = await identity_overlap_duplicate_exists(
            session,
            identity_fields,
            tenant_id=tenant_id,
        )
        if existing is not None:
            kind: MatchKind = "identity_overlap"
            # Filename may boost audit detail but does not change the hard match kind.
            if normalized_filename and (existing.normalized_filename or "") == normalized_filename:
                kind = "filename_combo"
            return IngestDuplicateMatch(existing, kind, "T2")

    if check_page_fingerprints and page_fingerprints:
        from app.services.ingest.page_fingerprint_service import find_invoice_by_page_fingerprints

        existing = await find_invoice_by_page_fingerprints(
            session,
            tenant_id=tenant_id,  # type: ignore[arg-type]
            page_fingerprints=page_fingerprints,
        )
        if existing is not None:
            # Page FP is physical-page identity — same as content FP, never role-bypass.
            return IngestDuplicateMatch(existing, "page_fingerprint", "T3")

    return None


async def find_existing_ingest_duplicate(
    session: AsyncSession,
    *,
    tenant_id: int,
    file_hash: str,
    content_fingerprint: str | None = None,
    business_fingerprint: str | None = None,
    identity_fields: dict[str, str] | None = None,
    page_fingerprints: list[str] | None = None,
    check_page_fingerprints: bool = False,
    normalized_filename: str | None = None,
) -> Invoice | None:
    """Match by file hash, bundle source hash, business/content fingerprint, identity, or page FP."""
    match = await find_existing_ingest_duplicate_match(
        session,
        tenant_id=tenant_id,
        file_hash=file_hash,
        content_fingerprint=content_fingerprint,
        business_fingerprint=business_fingerprint,
        identity_fields=identity_fields,
        page_fingerprints=page_fingerprints,
        check_page_fingerprints=check_page_fingerprints,
        normalized_filename=normalized_filename,
    )
    return match.invoice if match else None


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
    slack_connection_id: int | None = None,
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
        slack_connection_id=slack_connection_id,
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
        **original_document_audit_fields(original),
        "file_hash": file_hash,
        "preserved_original_status": original.status.value,
    }
    if extra_detail:
        detail.update(extra_detail)
        # Keep original_* pointers authoritative even if callers pass a partial copy.
        detail.update(original_document_audit_fields(original))

    await log_duplicate_skipped(session, shadow.id, detail=detail)
    return shadow


@dataclass(frozen=True)
class IngestDuplicateOutcome:
    """Result of handling a duplicate during ingest."""

    handled: bool
    invoice_id: int | None = None
    existing: Invoice | None = None
    action: DuplicateAction | None = None
    match_kind: MatchKind | None = None
    confidence_tier: ConfidenceTier | None = None


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
    slack_connection_id: int | None = None,
    email_sender: str | None = None,
    email_subject: str | None = None,
    email_attachment_name: str | None = None,
    email_message_id: str | None = None,
    extra_detail: dict[str, Any] | None = None,
    match_kind: MatchKind | None = None,
    confidence_tier: ConfidenceTier | None = None,
) -> IngestDuplicateOutcome:
    """Apply the standard duplicate decision matrix for an ingest channel."""
    decision = evaluate_file_hash_duplicate(existing)
    tier = confidence_tier or (classify_match_tier(match_kind) if match_kind else None)
    detail: dict[str, Any] = {
        "filename": email_attachment_name,
        "source": capture_source or "upload",
        **(extra_detail or {}),
    }
    if content_fingerprint:
        detail["content_fingerprint"] = content_fingerprint
    if business_fingerprint:
        detail["business_fingerprint"] = business_fingerprint
    if match_kind:
        detail["match_kind"] = match_kind
    if tier:
        detail["confidence_tier"] = tier

    if decision.action == "allow":
        return IngestDuplicateOutcome(
            handled=False,
            existing=existing,
            action="allow",
            match_kind=match_kind,
            confidence_tier=tier,
        )

    await log_event(
        session,
        "duplicate_detected",
        invoice_id=existing.id,
        detail={
            **detail,
            "action": decision.action,
            **original_document_audit_fields(existing),
        },
    )

    if decision.action == "skip_in_progress":
        if email_message_id:
            existing.email_message_id = email_message_id
        await log_duplicate_in_progress(session, existing, detail=detail)
        return IngestDuplicateOutcome(
            handled=True,
            existing=existing,
            action=decision.action,
            match_kind=match_kind,
            confidence_tier=tier,
        )

    if decision.action == "skip_logged":
        if email_message_id:
            existing.email_message_id = email_message_id
        await log_event(
            session,
            "duplicate_skipped",
            invoice_id=existing.id,
            detail={
                **detail,
                "note": "repeat submission ignored",
                **original_document_audit_fields(existing),
            },
        )
        return IngestDuplicateOutcome(
            handled=True,
            existing=existing,
            action=decision.action,
            match_kind=match_kind,
            confidence_tier=tier,
        )

    if decision.action == "shadow_duplicate":
        shadow = await create_duplicate_shadow_invoice(
            session,
            tenant_id=tenant_id,
            original=existing,
            connected_mailbox_id=connected_mailbox_id,
            whatsapp_connection_id=whatsapp_connection_id,
            viber_connection_id=viber_connection_id,
            slack_connection_id=slack_connection_id,
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
            match_kind=match_kind,
            confidence_tier=tier,
        )

    if decision.action == "reingest_rejected":
        from app.services.approval.approval_service import restore_rejected_invoice_file_if_needed
        from app.services.invoice.invoice_reset import reset_invoice_for_reprocess

        if email_sender is not None:
            existing.email_sender = email_sender
        if email_subject is not None:
            existing.email_subject = email_subject
        if email_attachment_name is not None:
            existing.email_attachment_name = email_attachment_name
        if email_message_id is not None:
            existing.email_message_id = email_message_id
        await restore_rejected_invoice_file_if_needed(session, existing)
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
            match_kind=match_kind,
            confidence_tier=tier,
        )

    return IngestDuplicateOutcome(
        handled=True,
        existing=existing,
        action=decision.action,
        match_kind=match_kind,
        confidence_tier=tier,
    )


async def invoice_number_duplicate_exists(
    session: AsyncSession,
    data: InvoiceData,
    *,
    tenant_id: int,
    exclude_id: int | None = None,
    document_role: str | None = None,
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

    for row in (await session.execute(stmt)).scalars().all():
        if document_roles_conflict(document_role, document_role_from_invoice(row)):
            continue
        return row
    return None
