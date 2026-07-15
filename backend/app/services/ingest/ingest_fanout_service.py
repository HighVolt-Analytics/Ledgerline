"""Fan-out ingest: split multi-document PDFs into separate invoice rows."""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.credit_service import (
    assert_can_upload,
    charge_upload_credits,
)
from app.services.document_page_count import count_document_pages
from app.models.invoice import Invoice, InvoiceStatus
from app.services.audit.audit_service import log_event
from app.services.dossier.document_duplicate_service import (
    find_existing_ingest_duplicate,
    find_invoice_by_source_file_hash,
    resolve_ingest_duplicate,
)
from app.services.dossier.document_ref_service import allocate_next_document_ref
from app.services.shared.file_storage import store_invoice_pdf
from app.services.extraction.pdf_content_fingerprint import (
    compute_pdf_content_fingerprint,
    compute_pdf_content_fingerprint_from_pages,
)
from app.services.extraction.document_identity_service import (
    compute_business_fingerprint,
    compute_business_fingerprint_from_pages,
    extract_identity_fields,
    extract_identity_fields_from_pages,
    identity_field_keys_from_catalogue,
)
from app.services.classification.catalogue_page_signals import build_catalogue_page_matchers
from app.services.invoice.invoice_evaluation_service import load_config_for_tenant
from app.services.extraction.pdf_page_text_service import (
    PdfPageText,
    PdfPageTextExtraction,
    extract_pdf_page_texts,
    extract_pdf_page_texts_via_full_di,
)
from app.services.extraction.pdf_segment_service import (
    purchase_document_type_from_heading,
)
from app.services.extraction.pdf_segment_llm_service import segment_pdf_pages_smart
from app.services.extraction.pdf_split_service import extract_pdf_page_range_bytes, segment_upload_filename
from app.services.purchase.purchase_document_service import normalize_purchase_document_type
from app.services.master_data.vendor_resolver import UNKNOWN_SLUG
from app.utils.hashing import compute_sha256_bytes


class DuplicateUploadError(Exception):
    """Raised when a duplicate cannot be handled gracefully (legacy upload path)."""


@dataclass(frozen=True)
class IngestUploadResult:
    invoice_ids: list[int]
    segment_count: int
    parent_file_hash: str
    duplicate_handled: bool = False


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


async def _log_pdf_split_skipped(
    session: AsyncSession,
    *,
    reason: str,
    parent_file_hash: str,
    filename: str,
    page_count: int | None = None,
    thin_page_count: int | None = None,
    segment_count_detected: int | None = None,
) -> None:
    detail: dict[str, object] = {
        "reason": reason,
        "source_file_hash": parent_file_hash,
        "filename": filename,
    }
    if page_count is not None:
        detail["page_count"] = page_count
    if thin_page_count is not None:
        detail["thin_page_count"] = thin_page_count
    if segment_count_detected is not None:
        detail["segment_count_detected"] = segment_count_detected
    await log_event(session, "pdf_split_skipped", detail=detail)


async def _try_resolve_duplicate(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    file_hash: str,
    content_fingerprint: str | None,
    business_fingerprint: str | None = None,
    identity_fields: dict[str, str] | None = None,
    bundle_source_hash: str | None = None,
    source: IngestSourceMetadata | None,
    filename: str,
) -> tuple[int | None, bool]:
    """Return (invoice_id, handled) when duplicate handling ran."""
    meta = source or IngestSourceMetadata()
    lookup_hash = bundle_source_hash or file_hash
    existing = await find_existing_ingest_duplicate(
        session,
        tenant_id=tenant_id,
        file_hash=lookup_hash,
        content_fingerprint=content_fingerprint,
        business_fingerprint=business_fingerprint,
        identity_fields=identity_fields,
    )
    if existing is None:
        return None, False

    outcome = await resolve_ingest_duplicate(
        session,
        tenant_id=tenant_id,
        existing=existing,
        file_hash=file_hash,
        content_fingerprint=content_fingerprint,
        business_fingerprint=business_fingerprint,
        capture_source=meta.capture_source,
        connected_mailbox_id=meta.connected_mailbox_id,
        whatsapp_connection_id=meta.whatsapp_connection_id,
        viber_connection_id=meta.viber_connection_id,
        email_sender=meta.email_sender,
        email_subject=meta.email_subject,
        email_attachment_name=meta.email_attachment_name or filename,
        email_message_id=meta.email_message_id,
        extra_detail={
            "filename": filename,
            "bundle_source_hash": bundle_source_hash,
        },
    )
    if not outcome.handled:
        return None, False
    return outcome.invoice_id, True


def _identity_fields_from_page_range(
    pages: list[PdfPageText],
    start_page: int,
    end_page: int,
    *,
    custom_field_keys: list[str] | None,
) -> dict[str, str]:
    combined = "\n".join(
        page.text
        for page in pages[start_page : end_page + 1]
        if (page.text or "").strip()
    )
    return extract_identity_fields(combined, custom_field_keys=custom_field_keys)


def _business_fingerprint_from_page_range(
    pages: list[PdfPageText],
    start_page: int,
    end_page: int,
    *,
    custom_field_keys: list[str] | None,
) -> str | None:
    fields = _identity_fields_from_page_range(
        pages,
        start_page,
        end_page,
        custom_field_keys=custom_field_keys,
    )
    return compute_business_fingerprint(fields)


async def _try_resolve_bundle_duplicate(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    parent_hash: str,
    content_fingerprint: str | None,
    business_fingerprint: str | None,
    identity_fields: dict[str, str] | None,
    source: IngestSourceMetadata | None,
    filename: str,
) -> tuple[int | None, bool]:
    """Block re-ingest of an entire multi-document PDF already captured."""
    existing = await find_invoice_by_source_file_hash(
        session,
        parent_hash,
        tenant_id=tenant_id,
    )
    if existing is None:
        existing = await find_existing_ingest_duplicate(
            session,
            tenant_id=tenant_id,
            file_hash=parent_hash,
            content_fingerprint=content_fingerprint,
            business_fingerprint=business_fingerprint,
            identity_fields=identity_fields,
        )
    if existing is None:
        return None, False

    meta = source or IngestSourceMetadata()
    outcome = await resolve_ingest_duplicate(
        session,
        tenant_id=tenant_id,
        existing=existing,
        file_hash=parent_hash,
        content_fingerprint=content_fingerprint,
        business_fingerprint=business_fingerprint,
        capture_source=meta.capture_source,
        connected_mailbox_id=meta.connected_mailbox_id,
        whatsapp_connection_id=meta.whatsapp_connection_id,
        viber_connection_id=meta.viber_connection_id,
        email_sender=meta.email_sender,
        email_subject=meta.email_subject,
        email_attachment_name=meta.email_attachment_name or filename,
        email_message_id=meta.email_message_id,
        extra_detail={
            "filename": filename,
            "bundle_source_hash": parent_hash,
            "bundle_duplicate": True,
        },
    )
    if not outcome.handled:
        return None, False
    return outcome.invoice_id, True


async def _create_invoice_from_bytes(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    tenant_slug: str,
    tenant_name: str | None,
    filename: str,
    data: bytes,
    file_hash: str,
    content_fingerprint: str | None,
    business_fingerprint: str | None = None,
    identity_fields: dict[str, str] | None = None,
    bundle_source_hash: str | None = None,
    purchase_document_type: str | None,
    source: IngestSourceMetadata | None = None,
    log_upload_event: bool = True,
    page_count: int | None = None,
    actor_name: str | None = None,
    actor_email: str | None = None,
) -> tuple[int | None, bool]:
    duplicate_id, duplicate_handled = await _try_resolve_duplicate(
        session,
        tenant_id=tenant_id,
        file_hash=file_hash,
        content_fingerprint=content_fingerprint,
        business_fingerprint=business_fingerprint,
        identity_fields=identity_fields,
        bundle_source_hash=bundle_source_hash,
        source=source,
        filename=filename,
    )
    if duplicate_handled:
        return duplicate_id, True

    pages = page_count if page_count is not None else count_document_pages(data, filename)
    await assert_can_upload(session, tenant_id, pages=pages)

    meta = source or IngestSourceMetadata()
    attachment_name = meta.email_attachment_name or filename
    vendor_slug = meta.storage_vendor_slug or UNKNOWN_SLUG

    document_ref = await allocate_next_document_ref(session, tenant_id)
    extracted_fields: dict[str, str] | None = None
    if bundle_source_hash:
        extracted_fields = {"source_file_hash": bundle_source_hash}

    from app.models.tenant import Tenant
    from app.tenant_settings import tenant_currency

    tenant = await session.get(Tenant, tenant_id)
    is_manual_upload = (meta.capture_source or "").strip().lower() == "upload"
    uploader_name = ((actor_name or "").strip() or None) if is_manual_upload else None
    uploader_email = ((actor_email or "").strip() or None) if is_manual_upload else None
    inv = Invoice(
        tenant_id=tenant_id,
        connected_mailbox_id=meta.connected_mailbox_id,
        viber_connection_id=meta.viber_connection_id,
        whatsapp_connection_id=meta.whatsapp_connection_id,
        status=InvoiceStatus.PENDING,
        file_hash=file_hash,
        content_fingerprint=content_fingerprint,
        business_fingerprint=business_fingerprint,
        currency=tenant_currency(tenant),
        storage_vendor_slug=vendor_slug,
        purchase_document_type=purchase_document_type,
        email_sender=meta.email_sender,
        email_subject=meta.email_subject,
        email_message_id=meta.email_message_id,
        email_attachment_name=attachment_name,
        capture_source=meta.capture_source,
        uploaded_by_name=uploader_name,
        uploaded_by_email=uploader_email,
        matched_rule_ids=meta.matched_rule_ids,
        document_ref=document_ref,
        extracted_fields=extracted_fields,
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

    from app.services.sales.so_reference import ensure_invoice_so_reference

    ensure_invoice_so_reference(inv)

    if log_upload_event:
        await log_event(
            session,
            "invoice_uploaded",
            invoice_id=inv.id,
            detail={
                "path": stored,
                "vendor_slug": vendor_slug,
                "file_hash": file_hash,
                "content_fingerprint": content_fingerprint,
                "business_fingerprint": business_fingerprint,
            },
            actor_name=actor_name,
            actor_email=actor_email,
        )

    settings = get_settings()
    await charge_upload_credits(
        session,
        tenant_id,
        pages=pages,
        idempotency_key=file_hash,
        invoice_id=inv.id,
        filename=filename,
        document_ai_provider=settings.default_document_ai_provider,
    )
    await session.flush()
    return inv.id, False


async def _single_file_ingest(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    tenant_slug: str,
    tenant_name: str | None,
    filename: str,
    data: bytes,
    file_hash: str,
    content_fingerprint: str | None,
    business_fingerprint: str | None = None,
    identity_fields: dict[str, str] | None = None,
    purchase_document_type: str | None,
    source: IngestSourceMetadata | None,
    log_upload_event: bool,
    parent_file_hash: str,
    actor_name: str | None = None,
    actor_email: str | None = None,
) -> IngestUploadResult:
    invoice_id, duplicate_handled = await _create_invoice_from_bytes(
        session,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
        filename=filename,
        data=data,
        file_hash=file_hash,
        content_fingerprint=content_fingerprint,
        business_fingerprint=business_fingerprint,
        identity_fields=identity_fields,
        purchase_document_type=purchase_document_type,
        source=source,
        log_upload_event=log_upload_event,
        actor_name=actor_name,
        actor_email=actor_email,
    )
    invoice_ids = [invoice_id] if invoice_id is not None else []
    return IngestUploadResult(
        invoice_ids=invoice_ids,
        segment_count=1 if invoice_id is not None else 0,
        parent_file_hash=parent_file_hash,
        duplicate_handled=duplicate_handled,
    )


async def ingest_file_with_fanout(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    tenant_slug: str,
    tenant_name: str | None,
    filename: str,
    data: bytes,
    purchase_document_type: str | None = None,
    source: IngestSourceMetadata | None = None,
    log_upload_event: bool = False,
    prefetched_extraction: PdfPageTextExtraction | None = None,
    actor_name: str | None = None,
    actor_email: str | None = None,
) -> IngestUploadResult:
    """
    Create one or more pending invoices from an attachment.

    PDFs may be split when multiple document headings are detected; other
    capture types always create a single invoice row.
    """
    meta = source or IngestSourceMetadata()
    channel = (meta.capture_source or "upload").lower()
    if channel in {"whatsapp", "viber"}:
        from app.services.credit_service import PlanFeatureBlockedError, assert_can_ingest_via_channel

        try:
            await assert_can_ingest_via_channel(session, tenant_id, channel="social")
        except PlanFeatureBlockedError as exc:
            raise exc
    elif channel in {"email", "mailbox", "graph"}:
        from app.services.credit_service import PlanFeatureBlockedError, assert_can_ingest_via_channel

        try:
            await assert_can_ingest_via_channel(session, tenant_id, channel="email")
        except PlanFeatureBlockedError as exc:
            raise exc

    settings = get_settings()
    parent_hash = compute_sha256_bytes(data)
    normalized_type = normalize_purchase_document_type(purchase_document_type)
    safe_filename = (filename or "attachment.bin").strip() or "attachment.bin"
    filename = safe_filename
    lower_name = safe_filename.lower()
    content_fingerprint: str | None = None
    business_fingerprint: str | None = None
    identity_fields: dict[str, str] | None = None
    document_types = []
    custom_field_keys: list[str] = []
    catalogue_matchers = []

    if lower_name.endswith(".pdf"):
        config = await load_config_for_tenant(session, tenant_id)
        document_types = list(config.document_types)
        custom_field_keys = identity_field_keys_from_catalogue(document_types)
        catalogue_matchers = build_catalogue_page_matchers(document_types)

    if not lower_name.endswith(".pdf") or not settings.pdf_multi_document_split:
        if lower_name.endswith(".pdf"):
            tmp_fp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
                    handle.write(data)
                    tmp_fp_path = Path(handle.name)
                extraction = extract_pdf_page_texts(tmp_fp_path)
                pages_for_fp = extraction.pages
                content_fingerprint = compute_pdf_content_fingerprint_from_pages(pages_for_fp)
                identity_fields = extract_identity_fields_from_pages(
                    pages_for_fp,
                    custom_field_keys=custom_field_keys,
                )
                business_fingerprint = compute_business_fingerprint_from_pages(
                    pages_for_fp,
                    custom_field_keys=custom_field_keys,
                )
            finally:
                if tmp_fp_path is not None:
                    tmp_fp_path.unlink(missing_ok=True)

        result = await _single_file_ingest(
            session,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            tenant_name=tenant_name,
            filename=filename,
            data=data,
            file_hash=parent_hash,
            content_fingerprint=content_fingerprint,
            business_fingerprint=business_fingerprint,
            identity_fields=identity_fields,
            purchase_document_type=normalized_type,
            source=source,
            log_upload_event=log_upload_event,
            parent_file_hash=parent_hash,
            actor_name=actor_name,
            actor_email=actor_email,
        )
        return result

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(data)
            tmp_path = Path(handle.name)

        extraction = prefetched_extraction or extract_pdf_page_texts(tmp_path)
        pages = extraction.pages
        incomplete_ocr = extraction.incomplete_ocr_indices
        if not pages:
            await _log_pdf_split_skipped(
                session,
                reason="empty_text",
                parent_file_hash=parent_hash,
                filename=filename,
            )
            return await _single_file_ingest(
                session,
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                tenant_name=tenant_name,
                filename=filename,
                data=data,
                file_hash=parent_hash,
                content_fingerprint=content_fingerprint,
                business_fingerprint=business_fingerprint,
                identity_fields=identity_fields,
                purchase_document_type=normalized_type,
                source=source,
                log_upload_event=log_upload_event,
                parent_file_hash=parent_hash,
                actor_name=actor_name,
                actor_email=actor_email,
            )

        content_fingerprint = compute_pdf_content_fingerprint_from_pages(pages)
        identity_fields = extract_identity_fields_from_pages(
            pages,
            custom_field_keys=custom_field_keys,
        )
        business_fingerprint = compute_business_fingerprint_from_pages(
            pages,
            custom_field_keys=custom_field_keys,
        )

        if incomplete_ocr:
            await _log_pdf_split_skipped(
                session,
                reason="ocr_incomplete",
                parent_file_hash=parent_hash,
                filename=filename,
                page_count=len(pages),
                thin_page_count=len(incomplete_ocr),
            )

        if len(pages) > settings.pdf_segment_max_pages:
            await _log_pdf_split_skipped(
                session,
                reason="page_cap",
                parent_file_hash=parent_hash,
                filename=filename,
                page_count=len(pages),
            )
            return await _single_file_ingest(
                session,
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                tenant_name=tenant_name,
                filename=filename,
                data=data,
                file_hash=parent_hash,
                content_fingerprint=content_fingerprint,
                business_fingerprint=business_fingerprint,
                identity_fields=identity_fields,
                purchase_document_type=normalized_type,
                source=source,
                log_upload_event=log_upload_event,
                parent_file_hash=parent_hash,
                actor_name=actor_name,
                actor_email=actor_email,
            )

        segment_result = await segment_pdf_pages_smart(
            pages,
            max_segments=settings.pdf_segment_max_segments,
            document_types=document_types,
            custom_field_keys=custom_field_keys,
            catalogue_matchers=catalogue_matchers,
        )
        segments = segment_result.segments

        if (
            len(segments) <= 1
            and len(pages) > 1
            and not segment_result.cap_exceeded
            and segment_result.segmentation_method == "rules"
        ):
            fallback = extract_pdf_page_texts_via_full_di(tmp_path)
            if fallback is not None and fallback.pages:
                pages = fallback.pages
                incomplete_ocr = fallback.incomplete_ocr_indices
                content_fingerprint = compute_pdf_content_fingerprint_from_pages(pages)
                identity_fields = extract_identity_fields_from_pages(
                    pages,
                    custom_field_keys=custom_field_keys,
                )
                business_fingerprint = compute_business_fingerprint_from_pages(
                    pages,
                    custom_field_keys=custom_field_keys,
                )
                segment_result = await segment_pdf_pages_smart(
                    pages,
                    max_segments=settings.pdf_segment_max_segments,
                    document_types=document_types,
                    custom_field_keys=custom_field_keys,
                    catalogue_matchers=catalogue_matchers,
                )
                segments = segment_result.segments

        bundle_dup_id, bundle_dup_handled = await _try_resolve_bundle_duplicate(
            session,
            tenant_id=tenant_id,
            parent_hash=parent_hash,
            content_fingerprint=content_fingerprint,
            business_fingerprint=business_fingerprint,
            identity_fields=identity_fields,
            source=source,
            filename=filename,
        )
        if bundle_dup_handled:
            invoice_ids = [bundle_dup_id] if bundle_dup_id is not None else []
            return IngestUploadResult(
                invoice_ids=invoice_ids,
                segment_count=len(segments),
                parent_file_hash=parent_hash,
                duplicate_handled=True,
            )

        if len(segments) <= 1:
            skip_reason = "segment_cap_exceeded" if segment_result.cap_exceeded else "no_headings"
            await _log_pdf_split_skipped(
                session,
                reason=skip_reason,
                parent_file_hash=parent_hash,
                filename=filename,
                page_count=len(pages),
                segment_count_detected=segment_result.detected_boundary_count or None,
            )
            return await _single_file_ingest(
                session,
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                tenant_name=tenant_name,
                filename=filename,
                data=data,
                file_hash=parent_hash,
                content_fingerprint=content_fingerprint,
                business_fingerprint=business_fingerprint,
                identity_fields=identity_fields,
                purchase_document_type=normalized_type,
                source=source,
                log_upload_event=log_upload_event,
                parent_file_hash=parent_hash,
                actor_name=actor_name,
                actor_email=actor_email,
            )

        invoice_ids: list[int] = []
        segment_count = len(segments)
        duplicate_handled = False
        for index, segment in enumerate(segments):
            segment_bytes = extract_pdf_page_range_bytes(
                tmp_path,
                segment.start_page,
                segment.end_page,
            )
            segment_hash = compute_sha256_bytes(segment_bytes)
            segment_fingerprint = compute_pdf_content_fingerprint(
                pages,
                segment.start_page,
                segment.end_page,
            )
            segment_business_fp = _business_fingerprint_from_page_range(
                pages,
                segment.start_page,
                segment.end_page,
                custom_field_keys=custom_field_keys,
            )
            segment_identity = _identity_fields_from_page_range(
                pages,
                segment.start_page,
                segment.end_page,
                custom_field_keys=custom_field_keys,
            )
            segment_type = purchase_document_type_from_heading(segment.heading_kind)
            segment_name = segment_upload_filename(filename, index, segment_count)

            segment_pages = segment.end_page - segment.start_page + 1
            invoice_id, segment_duplicate = await _create_invoice_from_bytes(
                session,
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                tenant_name=tenant_name,
                filename=segment_name,
                data=segment_bytes,
                file_hash=segment_hash,
                content_fingerprint=segment_fingerprint,
                business_fingerprint=segment_business_fp,
                identity_fields=segment_identity,
                bundle_source_hash=parent_hash,
                purchase_document_type=segment_type,
                source=source,
                log_upload_event=log_upload_event,
                page_count=segment_pages,
                actor_name=actor_name,
                actor_email=actor_email,
            )
            if segment_duplicate:
                duplicate_handled = True
            if invoice_id is None:
                continue

            inv = await session.get(Invoice, invoice_id)
            if inv is not None and inv.status == InvoiceStatus.DUPLICATE_SKIPPED:
                continue

            invoice_ids.append(invoice_id)

            await log_event(
                session,
                "pdf_segmented",
                invoice_id=invoice_id,
                detail={
                    "source_file_hash": parent_hash,
                    "content_fingerprint": segment_fingerprint,
                    "business_fingerprint": segment_business_fp,
                    "identity_signature": segment.identity_signature,
                    "page_kind_token": segment.page_kind_token,
                    "segment_index": index,
                    "segment_count": segment_count,
                    "start_page": segment.start_page,
                    "end_page": segment.end_page,
                    "heading_kind": segment.heading_kind,
                    "boundary_confidence": segment.boundary_confidence,
                    "purchase_document_type": segment_type,
                    "segmentation_method": segment_result.segmentation_method,
                    "llm_reasoning": segment_result.llm_reasoning,
                    "prompt_version": settings.pdf_segment_llm_prompt_version,
                },
            )

        return IngestUploadResult(
            invoice_ids=invoice_ids,
            segment_count=segment_count,
            parent_file_hash=parent_hash,
            duplicate_handled=duplicate_handled,
        )
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


async def ingest_upload_file(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    tenant_slug: str,
    tenant_name: str | None,
    filename: str,
    data: bytes,
    purchase_document_type: str | None,
    actor_name: str | None = None,
    actor_email: str | None = None,
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
        source=IngestSourceMetadata(capture_source="upload"),
        log_upload_event=True,
        actor_name=actor_name,
        actor_email=actor_email,
    )
