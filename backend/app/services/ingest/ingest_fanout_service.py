"""Fan-out ingest: split multi-document PDFs into separate invoice rows."""

from __future__ import annotations

import asyncio
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
    ConfidenceTier,
    MatchKind,
    find_existing_ingest_duplicate_match,
    find_invoice_by_source_file_hash,
    resolve_ingest_duplicate,
    signals_are_sparse,
)
from app.services.ingest.filename_normalize import normalize_attachment_filename
from app.services.ingest.page_fingerprint_service import (
    collect_page_fingerprints,
    enrich_pages_for_fingerprints,
    persist_invoice_page_fingerprints,
)
from app.services.dossier.document_ref_service import allocate_next_document_ref
from app.services.shared.file_storage import store_invoice_pdf
from app.services.extraction.pdf_content_fingerprint import (
    compute_pdf_content_fingerprint,
    compute_pdf_content_fingerprint_from_pages,
)
from app.services.extraction.document_heading_utils import document_role_from_heading
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
    action: str = "allow"
    match_kind: MatchKind | None = None
    confidence_tier: ConfidenceTier = "T4"
    review_suggested: bool = False


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


@dataclass(frozen=True)
class _CreateInvoiceResult:
    invoice_id: int | None
    duplicate_handled: bool
    action: str = "allow"
    match_kind: MatchKind | None = None
    confidence_tier: ConfidenceTier = "T4"
    review_suggested: bool = False


def _result_from_create(
    created: _CreateInvoiceResult,
    *,
    parent_file_hash: str,
    segment_count: int = 1,
) -> IngestUploadResult:
    invoice_ids = [created.invoice_id] if created.invoice_id is not None else []
    return IngestUploadResult(
        invoice_ids=invoice_ids,
        segment_count=segment_count if created.invoice_id is not None else 0,
        parent_file_hash=parent_file_hash,
        duplicate_handled=created.duplicate_handled,
        action=created.action,
        match_kind=created.match_kind,
        confidence_tier=created.confidence_tier,
        review_suggested=created.review_suggested,
    )



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
    document_role: str | None = None,
) -> str | None:
    fields = _identity_fields_from_page_range(
        pages,
        start_page,
        end_page,
        custom_field_keys=custom_field_keys,
    )
    role = (document_role or "").strip().lower()
    if role:
        # Role is part of the fingerprint so invoice + packing list + DN that share
        # invoice/PO numbers do not violate uq_invoice_tenant_business_fingerprint.
        fields = {**fields, "document_role": role}
    return compute_business_fingerprint(fields)


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
    pages_for_page_fp: list[PdfPageText] | None = None,
) -> _CreateInvoiceResult | None:
    """Return create-result when duplicate handling ran; None when allow."""
    meta = source or IngestSourceMetadata()
    lookup_hash = bundle_source_hash or file_hash
    normalized_name = normalize_attachment_filename(
        meta.email_attachment_name or filename
    )

    match = await find_existing_ingest_duplicate_match(
        session,
        tenant_id=tenant_id,  # type: ignore[arg-type]
        file_hash=lookup_hash,
        content_fingerprint=content_fingerprint,
        business_fingerprint=business_fingerprint,
        identity_fields=identity_fields,
        normalized_filename=normalized_name,
        check_page_fingerprints=False,
    )

    # T3 last resort: page fingerprints only when T1/T2 miss.
    if match is None and pages_for_page_fp:
        page_fps = [fp for _, fp in collect_page_fingerprints(pages_for_page_fp)]
        if page_fps:
            match = await find_existing_ingest_duplicate_match(
                session,
                tenant_id=tenant_id,  # type: ignore[arg-type]
                file_hash=lookup_hash,
                content_fingerprint=None,
                business_fingerprint=None,
                identity_fields=None,
                page_fingerprints=page_fps,
                check_page_fingerprints=True,
                normalized_filename=normalized_name,
            )

    if match is None:
        return None

    outcome = await resolve_ingest_duplicate(
        session,
        tenant_id=tenant_id,  # type: ignore[arg-type]
        existing=match.invoice,
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
        match_kind=match.match_kind,
        confidence_tier=match.confidence_tier,
        extra_detail={
            "filename": filename,
            "normalized_filename": normalized_name,
            "bundle_source_hash": bundle_source_hash,
        },
    )
    if not outcome.handled:
        return None
    return _CreateInvoiceResult(
        invoice_id=outcome.invoice_id,
        duplicate_handled=True,
        action=outcome.action or "skip_logged",
        match_kind=outcome.match_kind or match.match_kind,
        confidence_tier=outcome.confidence_tier or match.confidence_tier,
        review_suggested=False,
    )


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
    pages_for_page_fp: list[PdfPageText] | None = None,
) -> _CreateInvoiceResult | None:
    """Block re-ingest of an entire multi-document PDF already captured."""
    existing = await find_invoice_by_source_file_hash(
        session,
        parent_hash,
        tenant_id=tenant_id,  # type: ignore[arg-type]
    )
    match_kind: MatchKind | None = "source_file_hash" if existing is not None else None
    confidence_tier: ConfidenceTier = "T1"
    if existing is None:
        from_match = await find_existing_ingest_duplicate_match(
            session,
            tenant_id=tenant_id,  # type: ignore[arg-type]
            file_hash=parent_hash,
            content_fingerprint=content_fingerprint,
            business_fingerprint=business_fingerprint,
            identity_fields=identity_fields,
            check_page_fingerprints=False,
            normalized_filename=normalize_attachment_filename(filename),
        )
        if from_match is not None:
            existing = from_match.invoice
            match_kind = from_match.match_kind
            confidence_tier = from_match.confidence_tier

    if existing is None and pages_for_page_fp:
        page_fps = [fp for _, fp in collect_page_fingerprints(pages_for_page_fp)]
        if page_fps:
            from_match = await find_existing_ingest_duplicate_match(
                session,
                tenant_id=tenant_id,  # type: ignore[arg-type]
                file_hash=parent_hash,
                page_fingerprints=page_fps,
                check_page_fingerprints=True,
            )
            if from_match is not None:
                existing = from_match.invoice
                match_kind = from_match.match_kind
                confidence_tier = from_match.confidence_tier

    if existing is None:
        return None

    meta = source or IngestSourceMetadata()
    outcome = await resolve_ingest_duplicate(
        session,
        tenant_id=tenant_id,  # type: ignore[arg-type]
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
        match_kind=match_kind,
        confidence_tier=confidence_tier,
        extra_detail={
            "filename": filename,
            "bundle_source_hash": parent_hash,
            "bundle_duplicate": True,
        },
    )
    if not outcome.handled:
        return None
    return _CreateInvoiceResult(
        invoice_id=outcome.invoice_id,
        duplicate_handled=True,
        action=outcome.action or "skip_logged",
        match_kind=outcome.match_kind or match_kind,
        confidence_tier=outcome.confidence_tier or confidence_tier,
    )


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
    pages_for_page_fp: list[PdfPageText] | None = None,
    charge_credits: bool = True,
) -> _CreateInvoiceResult:
    duplicate = await _try_resolve_duplicate(
        session,
        tenant_id=tenant_id,
        file_hash=file_hash,
        content_fingerprint=content_fingerprint,
        business_fingerprint=business_fingerprint,
        identity_fields=identity_fields,
        bundle_source_hash=bundle_source_hash,
        source=source,
        filename=filename,
        pages_for_page_fp=pages_for_page_fp,
    )
    if duplicate is not None:
        return duplicate

    pages = page_count if page_count is not None else count_document_pages(data, filename)
    await assert_can_upload(session, tenant_id, pages=pages)

    meta = source or IngestSourceMetadata()
    attachment_name = meta.email_attachment_name or filename
    normalized_name = normalize_attachment_filename(attachment_name)
    vendor_slug = meta.storage_vendor_slug or UNKNOWN_SLUG

    page_fp_list = (
        [fp for _, fp in collect_page_fingerprints(pages_for_page_fp)]
        if pages_for_page_fp
        else None
    )
    review_suggested = signals_are_sparse(
        content_fingerprint=content_fingerprint,
        business_fingerprint=business_fingerprint,
        identity_fields=identity_fields,
        page_fingerprints=page_fp_list,
    )

    document_ref = await allocate_next_document_ref(session, tenant_id)
    extracted_fields: dict[str, str] | None = None
    if bundle_source_hash:
        extracted_fields = {"source_file_hash": bundle_source_hash}

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
        normalized_filename=normalized_name,
        duplicate_review_suggested=review_suggested,
        # Empty until extraction corroborates an ISO code — never seed tenant
        # reporting currency (that caused AUD to stick on bare-$ / ₹ invoices).
        currency="",
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

    if pages_for_page_fp:
        await persist_invoice_page_fingerprints(
            session,
            tenant_id=tenant_id,
            invoice_id=inv.id,
            pages=pages_for_page_fp,
        )

    if review_suggested:
        await log_event(
            session,
            "duplicate_weak_signal",
            invoice_id=inv.id,
            detail={
                "filename": filename,
                "normalized_filename": normalized_name,
                "content_fingerprint": content_fingerprint,
                "business_fingerprint": business_fingerprint,
                "confidence_tier": "T4",
                "source": meta.capture_source or "upload",
            },
        )

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
                "normalized_filename": normalized_name,
                "duplicate_review_suggested": review_suggested,
            },
            actor_name=actor_name,
            actor_email=actor_email,
        )

    settings = get_settings()
    if charge_credits:
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
    return _CreateInvoiceResult(
        invoice_id=inv.id,
        duplicate_handled=False,
        action="allow_weak" if review_suggested else "allow",
        confidence_tier="T4",
        review_suggested=review_suggested,
    )


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
    pages_for_page_fp: list[PdfPageText] | None = None,
) -> IngestUploadResult:
    created = await _create_invoice_from_bytes(
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
        pages_for_page_fp=pages_for_page_fp,
    )
    return _result_from_create(created, parent_file_hash=parent_file_hash)


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

    When the capture channel is listed in ``CANONICAL_INTAKE_CHANNELS``, delegates to
    ``intake_document`` (validate + central audit). Otherwise runs the legacy core path.
    """
    meta = source or IngestSourceMetadata()
    from app.services.ingest.canonical_intake_service import (
        canonical_intake_enabled_for,
        intake_document,
    )

    if canonical_intake_enabled_for(meta.capture_source):
        outcome = await intake_document(
            session,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            tenant_name=tenant_name,
            filename=filename,
            data=data,
            source=meta,
            purchase_document_type=purchase_document_type,
            actor_name=actor_name,
            actor_email=actor_email,
            prefetched_extraction=prefetched_extraction,
            log_upload_event=log_upload_event,
            # Email/WA already filter types; upload validates in API or here.
            skip_validation=(meta.capture_source or "").lower() not in {"upload", ""},
        )
        return outcome.result

    return await _ingest_file_with_fanout_core(
        session,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
        filename=filename,
        data=data,
        purchase_document_type=purchase_document_type,
        source=source,
        log_upload_event=log_upload_event,
        prefetched_extraction=prefetched_extraction,
        actor_name=actor_name,
        actor_email=actor_email,
    )


async def _ingest_file_with_fanout_core(
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
    pages_for_fp: list[PdfPageText] | None = None

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
                extraction = prefetched_extraction
                if extraction is None or not extraction.pages:
                    extraction = await asyncio.to_thread(extract_pdf_page_texts, tmp_fp_path)
                pages_for_fp = await asyncio.to_thread(
                    enrich_pages_for_fingerprints,
                    tmp_fp_path,
                    extraction.pages,
                )
                if pages_for_fp:
                    content_fingerprint = compute_pdf_content_fingerprint_from_pages(
                        pages_for_fp
                    )
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

            bundle_dup = await _try_resolve_bundle_duplicate(
                session,
                tenant_id=tenant_id,
                parent_hash=parent_hash,
                content_fingerprint=content_fingerprint,
                business_fingerprint=business_fingerprint,
                identity_fields=identity_fields,
                source=source,
                filename=filename,
                pages_for_page_fp=pages_for_fp,
            )
            if bundle_dup is not None:
                return _result_from_create(
                    bundle_dup,
                    parent_file_hash=parent_hash,
                    segment_count=1,
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
            pages_for_page_fp=pages_for_fp,
        )

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(data)
            tmp_path = Path(handle.name)

        extraction = prefetched_extraction or await asyncio.to_thread(
            extract_pdf_page_texts, tmp_path
        )
        pages = (
            await asyncio.to_thread(enrich_pages_for_fingerprints, tmp_path, extraction.pages)
            or extraction.pages
        )
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
                pages_for_page_fp=pages,
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
            and incomplete_ocr
        ):
            fallback = await asyncio.to_thread(extract_pdf_page_texts_via_full_di, tmp_path)
            if fallback is not None and fallback.pages:
                pages = (
                    await asyncio.to_thread(enrich_pages_for_fingerprints, tmp_path, fallback.pages)
                    or fallback.pages
                )
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

        bundle_dup = await _try_resolve_bundle_duplicate(
            session,
            tenant_id=tenant_id,
            parent_hash=parent_hash,
            content_fingerprint=content_fingerprint,
            business_fingerprint=business_fingerprint,
            identity_fields=identity_fields,
            source=source,
            filename=filename,
            pages_for_page_fp=pages,
        )
        if bundle_dup is not None:
            return _result_from_create(
                bundle_dup,
                parent_file_hash=parent_hash,
                segment_count=max(1, len(segments)),
            )

        if len(segments) <= 1:
            skip_reason = (
                "segment_cap_exceeded" if segment_result.cap_exceeded else "no_headings"
            )
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
                pages_for_page_fp=pages,
            )

        invoice_ids: list[int] = []
        segment_count = len(segments)
        duplicate_handled = False
        last_action = "allow"
        last_match_kind: MatchKind | None = None
        last_tier: ConfidenceTier = "T4"
        last_review = False
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
            segment_type = purchase_document_type_from_heading(segment.heading_kind)
            segment_role = document_role_from_heading(segment.heading_kind)
            segment_business_fp = _business_fingerprint_from_page_range(
                pages,
                segment.start_page,
                segment.end_page,
                custom_field_keys=custom_field_keys,
                document_role=segment_role,
            )
            segment_identity = _identity_fields_from_page_range(
                pages,
                segment.start_page,
                segment.end_page,
                custom_field_keys=custom_field_keys,
            )
            if segment_role:
                segment_identity = {**segment_identity, "document_role": segment_role}
            segment_name = segment_upload_filename(filename, index, segment_count)
            segment_page_slice = pages[segment.start_page : segment.end_page + 1]

            segment_pages = segment.end_page - segment.start_page + 1
            created = await _create_invoice_from_bytes(
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
                pages_for_page_fp=segment_page_slice,
            )
            if created.duplicate_handled:
                duplicate_handled = True
            last_action = created.action
            last_match_kind = created.match_kind
            last_tier = created.confidence_tier
            last_review = created.review_suggested
            if created.invoice_id is None:
                continue

            inv = await session.get(Invoice, created.invoice_id)
            if inv is not None and inv.status == InvoiceStatus.DUPLICATE_SKIPPED:
                continue

            if inv is not None and segment_role:
                # Persist role so later same-type re-uploads still match supporting docs
                # that have no purchase_document_type (e.g. packing_list).
                extracted = dict(inv.extracted_fields or {})
                extracted["document_role"] = segment_role
                inv.extracted_fields = extracted

            invoice_ids.append(created.invoice_id)

            await log_event(
                session,
                "pdf_segmented",
                invoice_id=created.invoice_id,
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
            action=last_action,
            match_kind=last_match_kind,
            confidence_tier=last_tier,
            review_suggested=last_review,
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
    from app.services.ingest.canonical_intake_service import (
        IntakeValidationError,
        canonical_intake_enabled_for,
        intake_document,
    )

    source = IngestSourceMetadata(capture_source="upload")
    if canonical_intake_enabled_for("upload"):
        try:
            outcome = await intake_document(
                session,
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                tenant_name=tenant_name,
                filename=filename,
                data=data,
                source=source,
                purchase_document_type=purchase_document_type,
                actor_name=actor_name,
                actor_email=actor_email,
                log_upload_event=True,
            )
        except IntakeValidationError:
            raise
        return outcome.result

    return await ingest_file_with_fanout(
        session,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
        filename=filename,
        data=data,
        purchase_document_type=purchase_document_type,
        source=source,
        log_upload_event=True,
        actor_name=actor_name,
        actor_email=actor_email,
    )
