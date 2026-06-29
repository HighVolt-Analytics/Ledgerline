"""Fan-out ingest: split multi-document PDFs into separate invoice rows."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.services.audit_service import log_event
from app.services.document_duplicate_service import find_invoice_by_file_hash
from app.services.document_ref_service import allocate_next_document_ref
from app.services.file_storage import store_invoice_pdf
from app.services.pdf_page_text_service import extract_pdf_page_texts
from app.services.pdf_segment_service import (
    purchase_document_type_from_heading,
    segment_pdf_pages,
)
from app.services.pdf_split_service import extract_pdf_page_range_bytes, segment_upload_filename
from app.services.purchase_document_service import normalize_purchase_document_type
from app.services.vendor_resolver import UNKNOWN_SLUG
from app.utils.hashing import compute_sha256_bytes


class DuplicateUploadError(Exception):
    """Raised when file hash already exists for this org."""


@dataclass(frozen=True)
class IngestUploadResult:
    invoice_ids: list[int]
    segment_count: int
    parent_file_hash: str


@dataclass
class IngestSourceMetadata:
    """Channel-specific fields applied to each created invoice row."""

    storage_vendor_slug: str = UNKNOWN_SLUG
    email_sender: str | None = None
    email_subject: str | None = None
    email_message_id: str | None = None
    email_attachment_name: str | None = None
    connected_mailbox_id: int | None = None
    viber_connection_id: int | None = None
    whatsapp_connection_id: int | None = None
    capture_source: str | None = None
    matched_rule_ids: str | None = None
    route_target: str | None = None


async def _create_invoice_from_bytes(
    session: AsyncSession,
    *,
    tenant_id: int,
    tenant_slug: str,
    tenant_name: str | None,
    filename: str,
    data: bytes,
    file_hash: str,
    purchase_document_type: str | None,
    source: IngestSourceMetadata | None = None,
    log_upload_event: bool = True,
) -> int:
    existing = await find_invoice_by_file_hash(session, file_hash, tenant_id=tenant_id)
    if existing is not None:
        raise DuplicateUploadError("Duplicate file already uploaded")

    meta = source or IngestSourceMetadata()
    attachment_name = meta.email_attachment_name or filename
    vendor_slug = meta.storage_vendor_slug or UNKNOWN_SLUG

    document_ref = await allocate_next_document_ref(session, tenant_id)
    inv = Invoice(
        tenant_id=tenant_id,
        connected_mailbox_id=meta.connected_mailbox_id,
        viber_connection_id=meta.viber_connection_id,
        whatsapp_connection_id=meta.whatsapp_connection_id,
        status=InvoiceStatus.PENDING,
        file_hash=file_hash,
        currency="AUD",
        storage_vendor_slug=vendor_slug,
        purchase_document_type=purchase_document_type,
        email_sender=meta.email_sender,
        email_subject=meta.email_subject,
        email_message_id=meta.email_message_id,
        email_attachment_name=attachment_name,
        capture_source=meta.capture_source,
        matched_rule_ids=meta.matched_rule_ids,
        document_ref=document_ref,
    )
    session.add(inv)
    await session.flush()

    stored = store_invoice_pdf(
        data,
        tenant_id,
        tenant_slug,
        vendor_slug,
        inv.id,
        file_hash,
        filename,
        tenant_name=tenant_name,
        purchase_document_type=purchase_document_type,
        route_target=meta.route_target,
    )
    inv.raw_file_path = stored

    if log_upload_event:
        await log_event(
            session,
            "invoice_uploaded",
            invoice_id=inv.id,
            detail={"path": stored, "vendor_slug": vendor_slug, "file_hash": file_hash},
        )
    await session.flush()
    return inv.id


async def ingest_file_with_fanout(
    session: AsyncSession,
    *,
    tenant_id: int,
    tenant_slug: str,
    tenant_name: str | None,
    filename: str,
    data: bytes,
    purchase_document_type: str | None = None,
    source: IngestSourceMetadata | None = None,
    log_upload_event: bool = False,
) -> IngestUploadResult:
    """
    Create one or more pending invoices from an attachment.

    PDFs may be split when multiple document headings are detected; other
    capture types always create a single invoice row.
    """
    settings = get_settings()
    parent_hash = compute_sha256_bytes(data)
    normalized_type = normalize_purchase_document_type(purchase_document_type)
    lower_name = filename.lower()

    if not lower_name.endswith(".pdf") or not settings.pdf_multi_document_split:
        invoice_id = await _create_invoice_from_bytes(
            session,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            tenant_name=tenant_name,
            filename=filename,
            data=data,
            file_hash=parent_hash,
            purchase_document_type=normalized_type,
            source=source,
            log_upload_event=log_upload_event,
        )
        return IngestUploadResult(invoice_ids=[invoice_id], segment_count=1, parent_file_hash=parent_hash)

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(data)
            tmp_path = Path(handle.name)

        pages = extract_pdf_page_texts(tmp_path)
        if not pages or len(pages) > settings.pdf_segment_max_pages:
            invoice_id = await _create_invoice_from_bytes(
                session,
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                tenant_name=tenant_name,
                filename=filename,
                data=data,
                file_hash=parent_hash,
                purchase_document_type=normalized_type,
                source=source,
                log_upload_event=log_upload_event,
            )
            return IngestUploadResult(
                invoice_ids=[invoice_id],
                segment_count=1,
                parent_file_hash=parent_hash,
            )

        segments = segment_pdf_pages(pages, max_segments=settings.pdf_segment_max_segments)
        if len(segments) <= 1:
            invoice_id = await _create_invoice_from_bytes(
                session,
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                tenant_name=tenant_name,
                filename=filename,
                data=data,
                file_hash=parent_hash,
                purchase_document_type=normalized_type,
                source=source,
                log_upload_event=log_upload_event,
            )
            return IngestUploadResult(
                invoice_ids=[invoice_id],
                segment_count=1,
                parent_file_hash=parent_hash,
            )

        invoice_ids: list[int] = []
        segment_count = len(segments)
        for index, segment in enumerate(segments):
            segment_bytes = extract_pdf_page_range_bytes(
                tmp_path,
                segment.start_page,
                segment.end_page,
            )
            segment_hash = compute_sha256_bytes(segment_bytes)
            segment_type = normalized_type or purchase_document_type_from_heading(segment.heading_kind)
            segment_name = segment_upload_filename(filename, index, segment_count)

            invoice_id = await _create_invoice_from_bytes(
                session,
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                tenant_name=tenant_name,
                filename=segment_name,
                data=segment_bytes,
                file_hash=segment_hash,
                purchase_document_type=segment_type,
                source=source,
                log_upload_event=False,
            )
            invoice_ids.append(invoice_id)

            await log_event(
                session,
                "pdf_segmented",
                invoice_id=invoice_id,
                detail={
                    "source_file_hash": parent_hash,
                    "segment_index": index,
                    "segment_count": segment_count,
                    "start_page": segment.start_page,
                    "end_page": segment.end_page,
                    "heading_kind": segment.heading_kind,
                    "boundary_confidence": segment.boundary_confidence,
                    "purchase_document_type": segment_type,
                },
            )

        return IngestUploadResult(
            invoice_ids=invoice_ids,
            segment_count=segment_count,
            parent_file_hash=parent_hash,
        )
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


async def ingest_upload_file(
    session: AsyncSession,
    *,
    tenant_id: int,
    tenant_slug: str,
    tenant_name: str | None,
    filename: str,
    data: bytes,
    purchase_document_type: str | None,
) -> IngestUploadResult:
    """Upload API entry point — logs invoice_uploaded for single-file ingest."""
    return await ingest_file_with_fanout(
        session,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
        filename=filename,
        data=data,
        purchase_document_type=purchase_document_type,
        log_upload_event=True,
    )
