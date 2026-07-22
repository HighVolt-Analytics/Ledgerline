"""Persist and look up per-page content fingerprints for ingest dedupe."""

from __future__ import annotations

import uuid
from collections import defaultdict

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.invoice_page_fingerprint import InvoicePageFingerprint
from app.services.extraction.pdf_content_fingerprint import (
    compute_pdf_content_fingerprint,
    normalize_pdf_text_blob,
)
from app.services.extraction.pdf_page_text_service import PdfPageText

# Short boilerplate pages (headers/footers) must not alone drive T3 matches.
_MIN_PAGE_TEXT_CHARS = 80

_LOOKUP_IGNORE = frozenset(
    {
        InvoiceStatus.DUPLICATE_SKIPPED,
    }
)


def page_fingerprint_for_index(pages: list[PdfPageText], page_index: int) -> str | None:
    """Fingerprint a single page when it has enough normalized text."""
    if page_index < 0 or page_index >= len(pages):
        return None
    normalized = normalize_pdf_text_blob(pages[page_index].text)
    if len(normalized) < _MIN_PAGE_TEXT_CHARS:
        return None
    return compute_pdf_content_fingerprint(pages, page_index, page_index)


def collect_page_fingerprints(pages: list[PdfPageText]) -> list[tuple[int, str]]:
    """Return (page_index, fingerprint) for pages that meet the text threshold."""
    out: list[tuple[int, str]] = []
    for index in range(len(pages)):
        fp = page_fingerprint_for_index(pages, index)
        if fp:
            out.append((index, fp))
    return out


def required_page_fingerprint_matches(incoming_count: int) -> int:
    """
    How many page FPs must overlap for a T3 hard match.

    Single-page uploads still match on one page. Multi-page uploads require at least
    two overlapping pages (or a majority) so a shared Ts&Cs / cover page alone cannot
    mark unrelated files of the same type as duplicates.
    """
    if incoming_count <= 1:
        return 1
    return max(2, (incoming_count + 1) // 2)


def enrich_pages_for_fingerprints(
    path: Path,
    pages: list[PdfPageText] | None,
) -> list[PdfPageText] | None:
    """
    If local/hybrid extract cannot produce page fingerprints, try full DI once.

    Never invents fingerprints: empty after DI stays empty (T4 weak-signal path).
    """
    from app.services.extraction.pdf_page_text_service import (
        extract_pdf_page_texts_via_full_di,
    )

    if pages and collect_page_fingerprints(pages):
        return pages

    fallback = extract_pdf_page_texts_via_full_di(path)
    if fallback is not None and fallback.pages:
        if collect_page_fingerprints(fallback.pages):
            return fallback.pages
        # DI returned text but still below FP threshold — prefer DI pages for
        # content/business fingerprints when local was empty/thin.
        if not pages or not any((p.text or "").strip() for p in pages):
            return fallback.pages
    return pages


async def persist_invoice_page_fingerprints(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
    pages: list[PdfPageText] | None,
) -> int:
    """Store page fingerprints for an invoice (replace existing rows for that invoice).

    Safe to call again on reprocess — prior page fingerprint rows for the same
    invoice_id are cleared before insert.
    """
    if not pages:
        return 0
    pairs = collect_page_fingerprints(pages)
    if not pairs:
        return 0

    from sqlalchemy import delete

    await session.execute(
        delete(InvoicePageFingerprint).where(
            InvoicePageFingerprint.invoice_id == invoice_id,
            InvoicePageFingerprint.tenant_id == tenant_id,
        )
    )
    for page_index, fingerprint in pairs:
        session.add(
            InvoicePageFingerprint(
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                page_index=page_index,
                page_fingerprint=fingerprint,
            )
        )
    await session.flush()
    return len(pairs)


async def find_invoice_by_page_fingerprints(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    page_fingerprints: list[str],
) -> Invoice | None:
    """Return the oldest non-shadow invoice with enough overlapping page fingerprints."""
    if not page_fingerprints:
        return None
    unique = list(dict.fromkeys(fp for fp in page_fingerprints if fp))
    if not unique:
        return None
    need = required_page_fingerprint_matches(len(unique))

    stmt = (
        select(Invoice, InvoicePageFingerprint.page_fingerprint)
        .join(
            InvoicePageFingerprint,
            InvoicePageFingerprint.invoice_id == Invoice.id,
        )
        .where(
            InvoicePageFingerprint.tenant_id == tenant_id,
            InvoicePageFingerprint.page_fingerprint.in_(unique),
            Invoice.tenant_id == tenant_id,
            Invoice.status.notin_(_LOOKUP_IGNORE),
        )
        .order_by(Invoice.created_at.asc())
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return None

    counts: dict[int, set[str]] = defaultdict(set)
    invoices: dict[int, Invoice] = {}
    for invoice, fingerprint in rows:
        invoices[invoice.id] = invoice
        counts[invoice.id].add(fingerprint)

    for invoice_id, matched in counts.items():
        if len(matched) >= need:
            return invoices[invoice_id]
    return None
