"""Run the invoice processing pipeline for one PDF."""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import flag_enabled_for_dt, get_settings
from app.services.shared.amount_sanity import plausible_money, sanitize_parsed_line_item
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.models.journal import JournalEntry
from app.models.line_item import LineItem
from app.models.vendor import VendorRegistry
from app.models.customer import CustomerRegistry
from app.services.rule_book.account_mapper import AccountMapping, MappingDetail
from app.services.dossier.document_duplicate_service import (
    find_existing_ingest_duplicate,
    find_invoice_by_file_hash,
    resolve_ingest_duplicate,
)
from app.services.dossier.document_ref_service import assign_document_ref, audit_document_detail
from app.services.ingest.ingest_capture_service import apply_ingest_capture, evaluate_ingest_capture
from app.services.approval.approval_pipeline_service import (
    human_approval_may_bypass_validation,
    human_approved_payable_bypass,
)
from app.services.ingest.ingest_fanout_service import IngestSourceMetadata, ingest_file_with_fanout
from app.services.invoice.processing_override_catalog import (
    clear_processing_overrides,
    override_bypasses_purchase_hold,
    should_skip,
    skip_steps_for,
)
from app.services.invoice.invoice_evaluation_service import (
    EVAL_AUTO_CODED as EVAL_STATUS_AUTO_CODED,
    EVAL_AWAITING_CLASSIFICATION,
    EVAL_NEEDS_RESCAN,
    EVAL_NEEDS_REVIEW,
    EVAL_PENDING_VENDOR,
    ROUTE_EXPENSES,
    ROUTE_PURCHASE,
    ROUTE_SALES,
    ROUTE_TEAM,
    ROUTE_VAULT,
    apply_invoice_evaluation,
    load_config_for_tenant,
)
from app.services.invoice.routing_review_service import (
    requires_gl_mapping_review,
    requires_playbook_review,
)
from app.services.classification.classification_learning_service import (
    few_shot_examples_for_tenant,
    human_confirmed_document_type,
    resolve_vendor_learning_key,
)
from app.services.classification.classification_drift_service import (
    check_vendor_classification_drift,
    drift_audit_detail,
)
from app.services.extraction.di_extract_service import OcrFailed
from app.services.extraction.document_ai_provider import (
    DocumentAiProvider,
    extract_fields,
)
from app.services.invoice.invoice_pipeline_phases import (
    apply_user_defined_classifier_gate,
    backfill_llm_dt_from_policy,
    reconcile_llm_dt_with_heading,
    evaluate_confidence_gate,
    evaluate_field_confidence_gate,
    evaluate_image_quality_gate,
    field_confidence_audit_detail,
    gate_audit_detail,
    image_quality_audit_detail,
    phase_llm_classify,
    persist_llm_party_context,
    phase_file_validity,
    phase_ocr,
    phase_storage_verify,
)
from app.services.extraction.llm_document_service import (
    apply_document_type_to_invoice,
    llm_result_to_invoice_data,
)
from app.schemas.classification_decision import ReviewReason
from app.services.tenant.tenant_org_context import ai_classification_from_config
from app.schemas.llm_document import LlmDocumentResult
from app.services.tenant.tenant_org_context import org_context_from_config
from app.services.vault.vault_paths import filename_from_stored
from app.services.classification.document_type_catalog import get_document_type_definition
from app.services.classification.document_type_playbook_service import (
    evaluate_playbook_gates,
    resolve_definition_for_invoice,
)
from app.services.classification.document_type_approval_service import apply_document_type_approval_gate
from app.services.classification.document_type_playbook_profile_service import playbook_policy_audit_detail
from app.services.rule_book.rule_book_mapper import is_fallback_mapping, map_invoice_with_details
from app.services.purchase.team_expense_approval import apply_team_expense_approval_gate
from app.services.purchase.team_expense_service import record_team_expense_processed
from app.services.purchase.team_expense_validator import has_receipt_attachment
from app.services.master_data.vendor_hold_service import apply_vendor_hold_if_needed
from app.services.master_data.bundle_vendor_service import reconcile_dossier_vendor, resolve_canonical_vendor_name
from app.services.master_data.vendor_name_utils import is_plausible_vendor_name
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem, invoice_data_from_invoice
from app.tenant_child_tables import journal_entries_for_invoice, line_items_for_invoice
from app.services.ingest.attachment_filter import filter_invoice_attachments
from app.services.audit.audit_detail_helpers import validation_audit_detail
from app.services.audit.audit_service import log_event
from app.services.ingest.capture_channel import infer_capture_channel, is_staff_claim_sender
from app.services.ingest.email_ingestion import RawEmail, mark_message_read
from app.services.shared.file_storage import open_pdf_for_reading
from app.services.vault.vault_blob_sync import sync_invoice_blob_path
from app.services.ingest.graph_mail_folders import folder_moves_enabled
from app.services.payments.journal_generator import generate_entries, is_balanced
from app.services.shared.notifier import send_notification
from app.services.reconciliation.reconciliation_service import reconcile_daily, save_reconciliation
from app.services.rule_book.validator import all_passed, results_to_json, run_all_validations
from app.services.master_data.vendor_resolver import (
    UNKNOWN_SLUG,
    is_valid_storage_slug,
    resolve_storage_slug_for_parsed_vendor,
)
from app.services.master_data.customer_resolver import resolve_capture_slug
from app.utils.hashing import compute_sha256_bytes


async def _log_processing_override_skip(
    session: AsyncSession,
    invoice: Invoice,
    step_id: str,
) -> None:
    await log_event(
        session,
        "pipeline_step_skipped",
        invoice_id=invoice.id,
        detail={"step_id": step_id, "source": "processing_override"},
    )


def _counterparty_registration_pending(invoice: Invoice) -> bool:
    """True when evaluation already flagged unknown vendor/customer registration."""
    return (invoice.evaluation_status or "").strip() == EVAL_PENDING_VENDOR


async def _vendor_hold_unless_skipped(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    if should_skip(invoice, "vendor_registration"):
        await _log_processing_override_skip(session, invoice, "vendor_registration")
        return False
    return await apply_vendor_hold_if_needed(session, invoice)


def _finalize_vendor_counterparty(
    invoice: Invoice,
    *,
    parsed: object | None,
    config: object,
) -> None:
    """Canonicalize AP vendor name on invoice.vendor after counterparty sync."""
    from app.services.extraction.extraction_field_values import extracted_fields_from_invoice
    from app.services.sales.counterparty_service import resolve_counterparty_side

    fields = extracted_fields_from_invoice(invoice)
    side = resolve_counterparty_side(
        route_target=invoice.route_target,
        perspective=fields.get("perspective") or fields.get("llm_perspective"),
    )
    if side != "vendor" or not invoice.vendor:
        return

    parsed_abn = getattr(parsed, "abn", None) if parsed is not None else invoice.abn
    canonical = resolve_canonical_vendor_name(
        invoice.tenant_id,
        vendor_names=[invoice.vendor],
        abns=[parsed_abn],
        config=config,
    )
    if canonical:
        invoice.vendor = canonical
    elif not is_plausible_vendor_name(invoice.vendor):
        invoice.vendor = None


async def _sync_counterparty_and_evaluate(
    session: AsyncSession,
    invoice: Invoice,
    *,
    parsed: object | None,
    config: object,
    org: object,
) -> None:
    """Sync finance counterparty on invoice.vendor, then evaluate routing/match."""
    from app.services.sales.counterparty_service import sync_invoice_counterparty

    sync_invoice_counterparty(invoice, config=config, parsed=parsed, org=org)
    _finalize_vendor_counterparty(invoice, parsed=parsed, config=config)
    await apply_invoice_evaluation(session, invoice, config=config)
    prior_vendor = invoice.vendor
    sync_invoice_counterparty(invoice, config=config, parsed=parsed, org=org)
    _finalize_vendor_counterparty(invoice, parsed=parsed, config=config)
    if (invoice.vendor or "") != (prior_vendor or ""):
        await apply_invoice_evaluation(session, invoice, config=config)


async def _sync_and_evaluate_invoice(
    session: AsyncSession,
    invoice: Invoice,
    *,
    parsed: object | None = None,
    config: object | None = None,
    org: object | None = None,
) -> None:
    """Load pipeline context when needed, then sync counterparty and evaluate."""
    if config is None:
        config = await load_config_for_tenant(session, invoice.tenant_id)
    if org is None:
        tenant_row = await session.get(Tenant, invoice.tenant_id)
        org = org_context_from_config(config, tenant_row)
    if parsed is None:
        from app.services.invoice.invoice_data import invoice_data_from_invoice

        parsed = invoice_data_from_invoice(invoice)
    await _sync_counterparty_and_evaluate(
        session,
        invoice,
        parsed=parsed,
        config=config,
        org=org,
    )


async def _clear_purchase_awaiting_po_if_overridden(
    session: AsyncSession,
    invoice: Invoice,
    loaded: Invoice,
) -> None:
    from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED
    from app.services.purchase.purchase_document_service import EVAL_AWAITING_PO

    if not override_bypasses_purchase_hold(invoice):
        return
    if loaded.evaluation_status != EVAL_AWAITING_PO:
        return
    await _log_processing_override_skip(session, invoice, "playbook")
    loaded.evaluation_status = EVAL_AUTO_CODED
    loaded.status = InvoiceStatus.PARSING
    invoice.evaluation_status = EVAL_AUTO_CODED
    invoice.status = InvoiceStatus.PARSING
    await session.flush()


def _mark_invoice_processed(invoice: Invoice) -> None:
    clear_processing_overrides(invoice)
    invoice.status = InvoiceStatus.PROCESSED


@dataclass
class EmailIngestResult:
    ingested_count: int = 0
    message_ids: list[str] = field(default_factory=list)
    preskip_exceptions: dict[str, str] = field(default_factory=dict)


def _filename_from_stored(stored: str, invoice_id: int, file_hash: str) -> str:
    _ = (invoice_id, file_hash)
    return filename_from_stored(stored)


def _scalar_field_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _apply_parsed_scalar(invoice: Invoice, field: str, value: object) -> None:
    if not _scalar_field_empty(getattr(invoice, field)):
        return
    setattr(invoice, field, value)


async def _replace_line_items(
    session: AsyncSession,
    invoice: Invoice,
    lines: list[ParsedLineItem],
) -> None:
    stale = list(invoice.line_items)
    if stale:
        for item in stale:
            await session.delete(item)
    else:
        await session.execute(
            delete(LineItem).where(
                *line_items_for_invoice(invoice.tenant_id, invoice.id),
            )
        )
    invoice.line_items.clear()
    await session.flush()
    for line in lines:
        cleaned = sanitize_parsed_line_item(line)
        invoice.line_items.append(
            LineItem(
                tenant_id=invoice.tenant_id,
                invoice_id=invoice.id,
                description=cleaned.description,
                qty=cleaned.qty,
                unit_price=cleaned.unit_price,
                amount=cleaned.amount,
                tax_amount=cleaned.tax_amount,
            )
        )
    await session.flush()


def _resolve_header_mapping(
    invoice: Invoice,
    *,
    config,
    purchase_order=None,
    sales_order=None,
) -> tuple[AccountMapping, MappingDetail]:
    """Map invoice header using unified classification config."""
    if not invoice.line_items:
        detail = map_invoice_with_details(
            invoice,
            config=config,
            purchase_order=purchase_order,
            sales_order=sales_order,
        )
        return (
            AccountMapping(
                account_code=detail.account_code,
                account_name=detail.account_name,
                expense_category=detail.expense_category,
            ),
            detail,
        )
    best_detail = map_invoice_with_details(
        invoice,
        config=config,
        purchase_order=purchase_order,
        sales_order=sales_order,
    )
    best = AccountMapping(
        account_code=best_detail.account_code,
        account_name=best_detail.account_name,
        expense_category=best_detail.expense_category,
    )
    for line in invoice.line_items:
        detail = map_invoice_with_details(
            invoice,
            config=config,
            line_description=line.description,
            purchase_order=purchase_order,
            sales_order=sales_order,
        )
        if not is_fallback_mapping(detail):
            return (
                AccountMapping(
                    account_code=detail.account_code,
                    account_name=detail.account_name,
                    expense_category=detail.expense_category,
                ),
                detail,
            )
    return best, best_detail


async def find_by_hash(
    session: AsyncSession,
    file_hash: str,
    *,
    tenant_id: int,
) -> Invoice | None:
    """Backward-compatible alias for file-hash lookup."""
    return await find_invoice_by_file_hash(session, file_hash, tenant_id=tenant_id)


async def _tenant_slug(session: AsyncSession, tenant_id: int) -> str:
    org = await session.get(Tenant, tenant_id)
    if org:
        return org.slug
    return get_settings().default_tenant_slug


async def _post_parse_relocate(
    session: AsyncSession,
    invoice: Invoice,
    parsed_vendor: str | None,
) -> None:
    await sync_invoice_blob_path(session, invoice, parsed_vendor=parsed_vendor)


async def _safe_auto_learn(session: AsyncSession, invoice: Invoice) -> None:
    """Post-process sender learning must not fail an otherwise successful pipeline."""
    try:
        await _auto_learn_sender(session, invoice)
        await _auto_learn_customer_sender(session, invoice)
    except Exception as exc:
        from app.utils.logger import get_logger

        get_logger(__name__).warning(
            "auto_learn_failed",
            invoice_id=invoice.id,
            error=str(exc),
        )


async def _auto_learn_sender(session: AsyncSession, invoice: Invoice) -> None:
    settings = get_settings()
    if not settings.blob_auto_learn_sender:
        return
    if not invoice.email_sender or not invoice.storage_vendor_slug:
        return
    if invoice.storage_vendor_slug == UNKNOWN_SLUG:
        return

    rows = (
        await session.execute(
            select(VendorRegistry).where(VendorRegistry.tenant_id == invoice.tenant_id)
        )
    ).scalars().all()
    for row in rows:
        if row.sender_pattern.lower() == invoice.email_sender.lower():
            return
        if row.vendor_slug == invoice.storage_vendor_slug:
            return

    session.add(
        VendorRegistry(
            tenant_id=invoice.tenant_id,
            vendor_slug=invoice.storage_vendor_slug,
            vendor_name=invoice.vendor or invoice.storage_vendor_slug,
            sender_pattern=invoice.email_sender,
            abn=invoice.abn,
            approved=False,
        )
    )
    await log_event(
        session,
        "vendor_sender_learned",
        invoice_id=invoice.id,
        detail={
            "sender": invoice.email_sender,
            "vendor_slug": invoice.storage_vendor_slug,
        },
    )


async def _auto_learn_customer_sender(session: AsyncSession, invoice: Invoice) -> None:
    settings = get_settings()
    if not settings.blob_auto_learn_sender:
        return
    if (invoice.route_target or "").strip() != ROUTE_SALES:
        return
    if not invoice.email_sender or not invoice.storage_vendor_slug:
        return
    if invoice.storage_vendor_slug == UNKNOWN_SLUG:
        return

    rows = (
        await session.execute(
            select(CustomerRegistry).where(CustomerRegistry.tenant_id == invoice.tenant_id)
        )
    ).scalars().all()
    for row in rows:
        if row.sender_pattern.lower() == invoice.email_sender.lower():
            return
        if row.customer_slug == invoice.storage_vendor_slug:
            return

    session.add(
        CustomerRegistry(
            tenant_id=invoice.tenant_id,
            customer_slug=invoice.storage_vendor_slug,
            customer_name=invoice.vendor or invoice.storage_vendor_slug,
            sender_pattern=invoice.email_sender,
            abn=invoice.abn,
            approved=False,
        )
    )
    await log_event(
        session,
        "customer_sender_learned",
        invoice_id=invoice.id,
        detail={
            "sender": invoice.email_sender,
            "customer_slug": invoice.storage_vendor_slug,
        },
    )


def _finish_email_message(
    message_id: str,
    mailbox_email: str,
    *,
    access_token: str | None = None,
) -> None:
    """Mark read when folder moves are disabled (legacy behaviour)."""
    if not folder_moves_enabled():
        mark_message_read(message_id, mailbox_email, access_token=access_token)


def _maybe_finish_email_message(
    email: RawEmail,
    *,
    mark_processed: bool,
    mark_processed_only_if_ingested: bool,
    ingested_before: int,
    ingested_after: int,
) -> None:
    if not mark_processed:
        return
    if mark_processed_only_if_ingested and ingested_after <= ingested_before:
        return
    _finish_email_message(
        email.message_id,
        email.mailbox_email,
        access_token=email.graph_access_token,
    )


async def ingest_email_attachments(
    session: AsyncSession,
    emails: list[RawEmail],
    *,
    tenant_id: int,
    tenant_slug: str,
    connected_mailbox_id: int | None = None,
    mark_processed: bool = True,
    mark_processed_only_if_ingested: bool = False,
    known_message_ids: frozenset[str] | None = None,
) -> EmailIngestResult:
    """Save invoice attachments (PDF/image/DOCX) from emails."""
    result = EmailIngestResult()
    org = await session.get(Tenant, tenant_id)
    tenant_name = org.name if org else None

    capture_config = await load_config_for_tenant(session, tenant_id)

    for email in emails:
        result.message_ids.append(email.message_id)

        if known_message_ids and email.message_id in known_message_ids:
            await log_event(
                session,
                "email_skipped",
                detail={
                    "reason": "message_already_imported",
                    "message_id": email.message_id,
                },
            )
            result.preskip_exceptions[email.message_id] = "message_already_imported"
            continue

        ingested_before = result.ingested_count

        if not email.attachments:
            await log_event(
                session,
                "email_skipped",
                detail={"reason": "no_attachments", "message_id": email.message_id},
            )
            result.preskip_exceptions[email.message_id] = "no_attachments"
            _maybe_finish_email_message(
                email,
                mark_processed=mark_processed,
                mark_processed_only_if_ingested=mark_processed_only_if_ingested,
                ingested_before=ingested_before,
                ingested_after=result.ingested_count,
            )
            continue

        attachments = filter_invoice_attachments(email)
        if not attachments:
            await log_event(
                session,
                "email_skipped",
                detail={"reason": "no_invoice_attachments", "message_id": email.message_id},
            )
            result.preskip_exceptions[email.message_id] = "no_invoice_attachments"
            _maybe_finish_email_message(
                email,
                mark_processed=mark_processed,
                mark_processed_only_if_ingested=mark_processed_only_if_ingested,
                ingested_before=ingested_before,
                ingested_after=result.ingested_count,
            )
            continue

        capture_rule_blocked = False
        for att in attachments:
            capture_rule = evaluate_ingest_capture(email, att, capture_config)
            if not capture_rule:
                capture_rule_blocked = True
                await log_event(
                    session,
                    "email_skipped",
                    detail={
                        "reason": "no_capture_rule_match",
                        "message_id": email.message_id,
                        "sender": email.sender,
                        "subject": email.subject,
                        "attachment": att.filename,
                        "mailbox": email.mailbox_email,
                    },
                )
                continue

            file_hash = compute_sha256_bytes(att.data)
            content_fingerprint: str | None = None
            business_fingerprint: str | None = None
            identity_fields: dict[str, str] | None = None
            prefetched_extraction = None
            if att.filename and att.filename.lower().endswith(".pdf"):
                import tempfile
                from pathlib import Path

                from app.services.extraction.document_identity_service import (
                    compute_business_fingerprint_from_pages,
                    extract_identity_fields_from_pages,
                    identity_field_keys_from_catalogue,
                )
                from app.services.extraction.pdf_content_fingerprint import (
                    compute_pdf_content_fingerprint_from_pages,
                )
                from app.services.extraction.pdf_page_text_service import extract_pdf_page_texts

                custom_keys = identity_field_keys_from_catalogue(capture_config.document_types)
                tmp_path: Path | None = None
                try:
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
                        handle.write(att.data)
                        tmp_path = Path(handle.name)
                    prefetched_extraction = extract_pdf_page_texts(tmp_path)
                    pages_for_fp = prefetched_extraction.pages
                    content_fingerprint = compute_pdf_content_fingerprint_from_pages(pages_for_fp)
                    identity_fields = extract_identity_fields_from_pages(
                        pages_for_fp,
                        custom_field_keys=custom_keys,
                    )
                    business_fingerprint = compute_business_fingerprint_from_pages(
                        pages_for_fp,
                        custom_field_keys=custom_keys,
                    )
                finally:
                    if tmp_path is not None:
                        tmp_path.unlink(missing_ok=True)
            existing = await find_existing_ingest_duplicate(
                session,
                tenant_id=tenant_id,
                file_hash=file_hash,
                content_fingerprint=content_fingerprint,
                business_fingerprint=business_fingerprint,
                identity_fields=identity_fields,
            )
            if existing is not None:
                outcome = await resolve_ingest_duplicate(
                    session,
                    tenant_id=tenant_id,
                    existing=existing,
                    file_hash=file_hash,
                    content_fingerprint=content_fingerprint,
                    business_fingerprint=business_fingerprint,
                    capture_source="email",
                    connected_mailbox_id=connected_mailbox_id,
                    email_sender=email.sender or None,
                    email_subject=email.subject or None,
                    email_attachment_name=att.filename,
                    email_message_id=email.message_id,
                    extra_detail={
                        "filename": att.filename,
                        "message_id": email.message_id,
                        "mailbox": email.mailbox_email,
                        "source": "email",
                    },
                )
                if outcome.handled:
                    if outcome.action == "reingest_rejected" and outcome.invoice_id is not None:
                        inv = await session.get(Invoice, outcome.invoice_id)
                        if inv is not None:
                            from app.services.sales.so_reference import ensure_invoice_so_reference

                            ensure_invoice_so_reference(inv)
                            await apply_ingest_capture(session, inv, email, att)
                            result.ingested_count += 1
                    continue

            vendor_slug = await resolve_capture_slug(
                session, email.sender, tenant_id=tenant_id
            )
            fanout = await ingest_file_with_fanout(
                session,
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                tenant_name=tenant_name,
                filename=att.filename,
                data=att.data,
                source=IngestSourceMetadata(
                    storage_vendor_slug=vendor_slug,
                    email_sender=email.sender or None,
                    email_subject=email.subject or None,
                    email_message_id=email.message_id,
                    email_attachment_name=att.filename,
                    connected_mailbox_id=connected_mailbox_id,
                    capture_source="email",
                ),
                prefetched_extraction=prefetched_extraction,
            )

            for segment_index, invoice_id in enumerate(fanout.invoice_ids):
                inv = await session.get(Invoice, invoice_id)
                assert inv is not None
                await apply_ingest_capture(session, inv, email, att)
                await log_event(
                    session,
                    "email_ingested",
                    invoice_id=inv.id,
                    detail={
                        "subject": email.subject,
                        "sender": email.sender,
                        "message_id": email.message_id,
                        "vendor_slug": vendor_slug,
                        "storage": inv.raw_file_path,
                        "parent_file_hash": fanout.parent_file_hash,
                        "segment_index": segment_index,
                        "segment_count": fanout.segment_count,
                    },
                )

            result.ingested_count += len(fanout.invoice_ids)

        if capture_rule_blocked and result.ingested_count == ingested_before:
            result.preskip_exceptions[email.message_id] = "no_capture_rule_match"

        _maybe_finish_email_message(
            email,
            mark_processed=mark_processed,
            mark_processed_only_if_ingested=mark_processed_only_if_ingested,
            ingested_before=ingested_before,
            ingested_after=result.ingested_count,
        )

    return result


async def _finish_purchase_supporting_document(session: AsyncSession, invoice: Invoice) -> None:
    """PO / GRN documents: sync register, skip AP journal and GL mapping."""
    from app.services.purchase.purchase_document_service import EVAL_AWAITING_PO, sync_purchase_document
    from app.services.purchase.purchase_match_service import load_purchase_order_for_invoice
    from app.services.invoice.non_posting_document_service import finish_non_posting_document
    from app.services.classification.document_type_playbook_profile_service import clear_invoice_gl_mapping

    loaded = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    linked_po = await load_purchase_order_for_invoice(session, loaded)
    await _sync_and_evaluate_invoice(session, loaded)
    await sync_invoice_blob_path(session, loaded, parsed_vendor=loaded.vendor)
    invoice.raw_file_path = loaded.raw_file_path
    invoice.route_target = loaded.route_target
    clear_invoice_gl_mapping(invoice)
    clear_invoice_gl_mapping(loaded)

    await sync_purchase_document(session, invoice)
    if invoice.evaluation_status == EVAL_AWAITING_PO:
        invoice.status = InvoiceStatus.EXCEPTION
        await session.flush()
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    if linked_po:
        await reconcile_dossier_vendor(
            session,
            invoice,
            linked_po,
            document_type=invoice.purchase_document_type,
        )

    await finish_non_posting_document(
        session,
        invoice,
        audit_event="purchase_document_processed",
        detail={"purchase_document_type": invoice.purchase_document_type},
    )
    await _safe_auto_learn(session, invoice)


async def _finish_sales_supporting_document(session: AsyncSession, invoice: Invoice) -> None:
    """SO / DN documents: sync register, skip AR journal and GL mapping."""
    from app.services.sales.sales_document_service import EVAL_AWAITING_SO, sync_sales_document
    from app.services.sales.sales_match_service import load_sales_order_for_invoice
    from app.services.invoice.non_posting_document_service import finish_non_posting_document
    from app.services.classification.document_type_playbook_profile_service import clear_invoice_gl_mapping

    loaded = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    await load_sales_order_for_invoice(session, loaded)
    await _sync_and_evaluate_invoice(session, loaded)
    await sync_invoice_blob_path(session, loaded, parsed_vendor=loaded.vendor)
    invoice.raw_file_path = loaded.raw_file_path
    invoice.route_target = loaded.route_target
    clear_invoice_gl_mapping(invoice)
    clear_invoice_gl_mapping(loaded)

    await sync_sales_document(session, invoice)
    if invoice.evaluation_status == EVAL_AWAITING_SO:
        invoice.status = InvoiceStatus.EXCEPTION
        await session.flush()
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    await finish_non_posting_document(
        session,
        invoice,
        audit_event="sales_document_processed",
        detail={"sales_document_type": invoice.sales_document_type},
    )
    await _safe_auto_learn(session, invoice)


async def _apply_parsed_to_invoice(
    session: AsyncSession,
    *,
    invoice: Invoice,
    loaded: Invoice,
    parsed: InvoiceData,
    config,
    preserve_existing: bool = False,
    org=None,
) -> str | None:
    """Write extracted AP fields onto invoice rows (post-classification extract phase)."""
    if preserve_existing:
        from app.utils.abn_validator import storage_abn

        resolved_vendor = (loaded.vendor or "").strip() or None
        if not resolved_vendor:
            resolved_vendor = resolve_canonical_vendor_name(
                invoice.tenant_id,
                vendor_names=[parsed.vendor],
                abns=[parsed.abn],
                config=config,
            )
            if not resolved_vendor and parsed.vendor and is_plausible_vendor_name(parsed.vendor):
                resolved_vendor = parsed.vendor
            if resolved_vendor:
                invoice.vendor = resolved_vendor
                loaded.vendor = resolved_vendor

        _apply_parsed_scalar(invoice, "abn", storage_abn(parsed.abn) if parsed.abn else None)
        _apply_parsed_scalar(invoice, "billing_address", parsed.billing_address)
        _apply_parsed_scalar(invoice, "bank_bsb", parsed.bank_bsb)
        _apply_parsed_scalar(invoice, "bank_account", parsed.bank_account)
        _apply_parsed_scalar(invoice, "invoice_no", parsed.invoice_no)
        _apply_parsed_scalar(invoice, "po_reference", parsed.po_reference)
        _apply_parsed_scalar(invoice, "cost_centre", parsed.cost_centre)
        _apply_parsed_scalar(invoice, "invoice_date", parsed.invoice_date)
        _apply_parsed_scalar(invoice, "due_date", parsed.due_date)
        _apply_parsed_scalar(invoice, "subtotal", plausible_money(parsed.subtotal))
        _apply_parsed_scalar(invoice, "gst", plausible_money(parsed.gst))
        _apply_parsed_scalar(invoice, "total", plausible_money(parsed.total))
        from app.services.extraction.gst_rate import resolve_gst_rate_percent

        _apply_parsed_scalar(invoice, "gst_rate", resolve_gst_rate_percent(parsed, allow_inference=False))
        if _scalar_field_empty(invoice.currency):
            invoice.currency = parsed.currency
        if _scalar_field_empty(invoice.document_text):
            from app.services.extraction.document_text import cap_document_text

            invoice.document_text = cap_document_text(parsed.document_text)
        if not loaded.line_items:
            await _replace_line_items(session, loaded, parsed.line_items)

        from app.services.extraction.extraction_field_values import apply_parsed_extraction_fields

        apply_parsed_extraction_fields(invoice, parsed)

        loaded.abn = invoice.abn
        loaded.billing_address = invoice.billing_address
        loaded.bank_bsb = invoice.bank_bsb
        loaded.bank_account = invoice.bank_account
        loaded.invoice_no = invoice.invoice_no
        loaded.po_reference = invoice.po_reference
        loaded.so_reference = invoice.so_reference
        loaded.cost_centre = invoice.cost_centre
        loaded.invoice_date = invoice.invoice_date
        loaded.due_date = invoice.due_date
        loaded.subtotal = invoice.subtotal
        loaded.gst = invoice.gst
        loaded.gst_rate = invoice.gst_rate
        loaded.total = invoice.total
        loaded.currency = invoice.currency
        loaded.document_text = invoice.document_text
        loaded.document_heading = invoice.document_heading
        loaded.extracted_fields = invoice.extracted_fields
        from app.services.sales.counterparty_service import sync_invoice_counterparty

        sync_invoice_counterparty(invoice, config=config, parsed=parsed, org=org)
        loaded.vendor = invoice.vendor
        return invoice.vendor

    from app.utils.abn_validator import storage_abn

    invoice.vendor = parsed.vendor
    invoice.abn = storage_abn(parsed.abn)
    parsed.abn = invoice.abn
    invoice.billing_address = parsed.billing_address
    invoice.bank_bsb = parsed.bank_bsb
    invoice.bank_account = parsed.bank_account
    from app.services.extraction.invoice_no_sanitizer import extract_invoice_no_from_text, sanitize_invoice_no

    invoice.invoice_no = sanitize_invoice_no(parsed.invoice_no) or extract_invoice_no_from_text(
        parsed.document_text or ""
    )
    invoice.po_reference = parsed.po_reference
    invoice.cost_centre = parsed.cost_centre
    invoice.invoice_date = parsed.invoice_date
    invoice.due_date = parsed.due_date
    invoice.subtotal = plausible_money(parsed.subtotal)
    invoice.gst = plausible_money(parsed.gst)
    invoice.total = plausible_money(parsed.total)
    from app.services.extraction.gst_rate import resolve_gst_rate_percent

    invoice.gst_rate = resolve_gst_rate_percent(parsed, allow_inference=False)
    invoice.currency = parsed.currency
    from app.services.extraction.document_text import cap_document_text
    from app.services.purchase.po_reference import ensure_invoice_po_reference, extract_po_reference_from_text

    invoice.document_text = cap_document_text(parsed.document_text)
    from app.services.extraction.extraction_field_values import apply_parsed_extraction_fields

    apply_parsed_extraction_fields(invoice, parsed)
    if not invoice.po_reference:
        extracted = extract_po_reference_from_text(invoice.document_text)
        if extracted:
            invoice.po_reference = extracted
            parsed.po_reference = extracted

    from app.services.sales.so_reference import ensure_invoice_so_reference, sanitize_cross_book_linkage_references

    ensure_invoice_so_reference(invoice)
    ensure_invoice_po_reference(invoice)
    sanitize_cross_book_linkage_references(invoice)

    from app.services.sales.counterparty_service import sync_invoice_counterparty

    sync_invoice_counterparty(invoice, config=config, parsed=parsed, org=org)
    _finalize_vendor_counterparty(invoice, parsed=parsed, config=config)

    loaded.vendor = invoice.vendor
    loaded.abn = invoice.abn
    loaded.billing_address = invoice.billing_address
    loaded.bank_bsb = invoice.bank_bsb
    loaded.bank_account = invoice.bank_account
    loaded.invoice_no = invoice.invoice_no
    loaded.po_reference = invoice.po_reference
    loaded.so_reference = invoice.so_reference
    loaded.cost_centre = invoice.cost_centre
    loaded.invoice_date = invoice.invoice_date
    loaded.due_date = invoice.due_date
    loaded.subtotal = invoice.subtotal
    loaded.gst = invoice.gst
    loaded.gst_rate = invoice.gst_rate
    loaded.total = invoice.total
    loaded.currency = invoice.currency
    loaded.document_text = invoice.document_text
    loaded.document_heading = invoice.document_heading
    loaded.extracted_fields = invoice.extracted_fields

    await _replace_line_items(session, loaded, parsed.line_items)
    return invoice.vendor


async def process_invoice(session: AsyncSession, invoice: Invoice) -> None:
    """Parse → validate → map → journal → reconcile for one invoice."""
    if invoice.status in (
        InvoiceStatus.PROCESSED,
        InvoiceStatus.DUPLICATE_SKIPPED,
        InvoiceStatus.REJECTED,
    ):
        return

    await assign_document_ref(session, invoice)

    bypass_review_gates = await human_approved_payable_bypass(session, invoice)
    from app.services.invoice.invoice_edit_service import invoice_has_manual_field_edits

    await session.refresh(invoice, attribute_names=["processing_overrides"])

    preserve_extracted_fields = bypass_review_gates or await invoice_has_manual_field_edits(
        session,
        invoice.id,
        tenant_id=invoice.tenant_id,
    )

    if not invoice.raw_file_path:
        invoice.status = InvoiceStatus.EXCEPTION
        await log_event(
            session,
            "parsing_failed",
            invoice_id=invoice.id,
            detail=audit_document_detail(invoice, reason="no_stored_path"),
        )
        return

    invoice.status = InvoiceStatus.PARSING
    await session.flush()

    tenant_row = await session.get(Tenant, invoice.tenant_id)
    config = await load_config_for_tenant(session, invoice.tenant_id)
    org = org_context_from_config(config, tenant_row)
    ai_cfg = ai_classification_from_config(config)
    doc_provider = DocumentAiProvider.from_config(ai_cfg.document_ai_provider)
    provider_token = doc_provider.value

    human_locked_dt = await human_confirmed_document_type(session, invoice_id=invoice.id)
    if human_locked_dt:
        locked_defn = get_document_type_definition(
            human_locked_dt,
            document_types=config.document_types,
        )
        if locked_defn is None or not locked_defn.enabled:
            human_locked_dt = None

    try:
        await phase_storage_verify(
            session,
            invoice,
            document_ai_provider=provider_token,
        )
        await phase_file_validity(
            session,
            invoice,
            document_ai_provider=provider_token,
        )
    except OcrFailed as exc:
        reason = str(exc) or "stored_file_missing"
        invoice.status = InvoiceStatus.EXCEPTION
        if reason in {"file_encrypted", "unsupported_file_type", "file_corrupted", "file_too_large", "file_empty"}:
            invoice.evaluation_status = EVAL_NEEDS_RESCAN
        await log_event(
            session,
            "parsing_failed",
            invoice_id=invoice.id,
            detail=audit_document_detail(
                invoice,
                reason=reason,
                path=invoice.raw_file_path,
                document_ai_provider=provider_token,
            ),
        )
        if reason in {"file_encrypted", "unsupported_file_type", "file_corrupted", "file_too_large", "file_empty"}:
            await log_event(
                session,
                "routing_review_required",
                invoice_id=invoice.id,
                detail={
                    "gate": "file_validity",
                    "review_reasons": [reason],
                    "document_ai_provider": provider_token,
                },
            )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    skip_classify_gate = bool(human_locked_dt)
    locked_dt_code = (invoice.document_type_code or "").strip().upper()
    classification_override = should_skip(invoice, "classification") and bool(locked_dt_code)
    if classification_override and not human_locked_dt:
        skip_classify_gate = True
    classify_llm: LlmDocumentResult | None = None
    gate_result = None
    vendor_drift_result = None
    confirmed_dt = human_locked_dt or (locked_dt_code if classification_override else "")

    try:
        ocr = await phase_ocr(
            session,
            invoice,
            org=org,
            document_types=config.document_types,
            doc_provider=doc_provider,
            provider_token=provider_token,
            human_locked_dt=human_locked_dt,
        )
    except OcrFailed as exc:
        invoice.status = InvoiceStatus.EXCEPTION
        if human_locked_dt:
            invoice.evaluation_status = EVAL_NEEDS_REVIEW
        else:
            invoice.evaluation_status = EVAL_AWAITING_CLASSIFICATION
        await log_event(
            session,
            "parsing_failed",
            invoice_id=invoice.id,
            detail=audit_document_detail(
                invoice,
                reason="ocr_failed",
                error=str(exc),
                document_ai_provider=provider_token,
            ),
        )
        if not human_locked_dt:
            await log_event(
                session,
                "routing_review_required",
                invoice_id=invoice.id,
                detail={
                    "gate": "classification",
                    "review_reasons": [ReviewReason.PROVIDER_UNAVAILABLE.value],
                    "document_ai_provider": provider_token,
                    "provider_unavailable": True,
                },
            )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    quality_result = evaluate_image_quality_gate(ocr, ai_cfg=ai_cfg)
    await log_event(
        session,
        "image_quality_gate_passed" if quality_result.passed else "image_quality_gate_failed",
        invoice_id=invoice.id,
        detail=image_quality_audit_detail(quality_result, provider_token=provider_token),
    )
    if not quality_result.passed:
        if should_skip(invoice, "image_quality"):
            await _log_processing_override_skip(session, invoice, "image_quality")
        else:
            invoice.status = InvoiceStatus.EXCEPTION
            invoice.evaluation_status = EVAL_NEEDS_RESCAN
            await log_event(
                session,
                "routing_review_required",
                invoice_id=invoice.id,
                detail={
                    "gate": "image_quality",
                    "review_reasons": quality_result.review_reasons,
                    "text_length": quality_result.text_length,
                    "sparse": quality_result.sparse,
                    "min_text_chars": quality_result.min_text_chars,
                    "document_ai_provider": provider_token,
                    "resubmit_hint": "Please resend a flat, well-lit scan or PDF.",
                },
            )
            send_notification(invoice, InvoiceStatus.EXCEPTION)
            return

    from app.services.invoice.invoice_reset import reset_invoice_for_reprocess
    from app.services.invoice.processing_override_catalog import consume_deferred_full_reset

    if consume_deferred_full_reset(invoice) and not preserve_extracted_fields:
        keep_dt = bool(human_locked_dt) or (
            classification_override and bool(locked_dt_code)
        ) or "classification" in skip_steps_for(invoice)
        await reset_invoice_for_reprocess(
            session,
            invoice,
            preserve_document_type=keep_dt,
            clear_overrides=False,
        )
        await session.flush()

    enabled_dt_codes = {
        (dt.code or "").strip().upper()
        for dt in config.document_types
        if dt.enabled and (dt.code or "").strip()
    }
    vendor_learning_key = resolve_vendor_learning_key(invoice)
    few_shots = await few_shot_examples_for_tenant(
        session,
        tenant_id=invoice.tenant_id,
        valid_dt_codes=enabled_dt_codes,
        vendor_key=vendor_learning_key,
        vendor_limit=ai_cfg.vendor_few_shot_limit,
    )

    if not skip_classify_gate:
        with open_pdf_for_reading(invoice.raw_file_path, tenant_id=invoice.tenant_id) as path:
            classify_llm = await phase_llm_classify(
                session,
                invoice,
                ocr=ocr,
                org=org,
                document_types=config.document_types,
                few_shots=few_shots,
                doc_provider=doc_provider,
                provider_token=provider_token,
                file_path=path,
            )
            if classify_llm is not None:
                persist_llm_party_context(invoice, classify_llm, org)
                await session.flush()

        vendor_drift_result = await check_vendor_classification_drift(
            session,
            tenant_id=invoice.tenant_id,
            invoice_id=invoice.id,
            vendor_key=vendor_learning_key,
            classify_llm=classify_llm,
            ai_cfg=ai_cfg,
        )
        if vendor_drift_result is not None:
            await log_event(
                session,
                "vendor_classification_drift"
                if vendor_drift_result.detected
                else "vendor_classification_baseline",
                invoice_id=invoice.id,
                detail=drift_audit_detail(vendor_drift_result),
            )

        classify_llm, heading_reconcile_detail = reconcile_llm_dt_with_heading(
            classify_llm,
            invoice=invoice,
            ocr=ocr,
            document_types=config.document_types,
            ai_cfg=ai_cfg,
        )
        if heading_reconcile_detail:
            invoice.llm_suggested_dt = (classify_llm.suggested_dt if classify_llm else None) or None
            if classify_llm is not None:
                invoice.llm_confidence = round(classify_llm.confidence, 4)
            await log_event(
                session,
                "classification_heading_reconcile",
                invoice_id=invoice.id,
                detail=heading_reconcile_detail,
            )

        classify_llm, policy_backfill_detail = backfill_llm_dt_from_policy(
            classify_llm,
            invoice=invoice,
            ocr=ocr,
            document_types=config.document_types,
            ai_cfg=ai_cfg,
        )
        if policy_backfill_detail:
            invoice.llm_suggested_dt = (classify_llm.suggested_dt if classify_llm else None) or None
            if classify_llm is not None:
                invoice.llm_confidence = round(classify_llm.confidence, 4)
            await log_event(
                session,
                "classification_policy_backfill",
                invoice_id=invoice.id,
                detail=policy_backfill_detail,
            )

        gate_result = evaluate_confidence_gate(
            classify_llm,
            document_types=config.document_types,
            ai_cfg=ai_cfg,
            provider_token=provider_token,
        )
        gate_result = apply_user_defined_classifier_gate(
            gate_result,
            invoice=invoice,
            ocr=ocr,
            document_types=config.document_types,
        )

        await log_event(
            session,
            "classification_gate_passed" if gate_result.passed else "classification_gate_failed",
            invoice_id=invoice.id,
            detail=gate_audit_detail(gate_result, provider_token=provider_token),
        )

        if not gate_result.passed:
            stmt = (
                select(Invoice)
                .where(Invoice.id == invoice.id)
                .options(selectinload(Invoice.line_items))
            )
            loaded = (await session.execute(stmt)).scalar_one()
            loaded.document_type_code = None
            loaded.document_type_confidence = None
            invoice.document_type_code = None
            invoice.document_type_confidence = None
            loaded.evaluation_status = EVAL_AWAITING_CLASSIFICATION
            invoice.evaluation_status = EVAL_AWAITING_CLASSIFICATION
            loaded.llm_suggested_dt = invoice.llm_suggested_dt
            loaded.llm_confidence = invoice.llm_confidence
            invoice.status = InvoiceStatus.EXCEPTION
            await log_event(
                session,
                "routing_review_required",
                invoice_id=invoice.id,
                detail={
                    "gate": "classification",
                    "compare_passed": False,
                    "document_type_code": None,
                    "document_type_confidence": None,
                    "route_target": None,
                    "review_reasons": gate_result.review_reasons,
                    "llm_suggested_dt": gate_result.llm_suggested_dt,
                    "llm_confidence": gate_result.llm_confidence,
                    "llm_reasoning": gate_result.llm_reasoning,
                    "min_route_confidence": gate_result.min_route_confidence,
                    "org_auto_route_min_confidence": gate_result.org_auto_route_min_confidence,
                    "dt_min_route_confidence": gate_result.dt_min_route_confidence,
                    "document_ai_provider": provider_token,
                },
            )
            from app.services.classification.classification_gap_event import (
                build_classification_gap_event,
                gap_event_audit_detail,
            )

            gap_event = build_classification_gap_event(
                org_id=str(invoice.tenant_id),
                invoice_id=invoice.id,
                ocr_text=ocr.text or "",
                candidates=[
                    {
                        "code": gate_result.llm_suggested_dt,
                        "confidence": gate_result.llm_confidence,
                    }
                ],
                chosen_dt=gate_result.confirmed_dt or gate_result.llm_suggested_dt or "",
            )
            await log_event(
                session,
                "classification_gap_event",
                invoice_id=invoice.id,
                detail=gap_event_audit_detail(gap_event),
            )
            send_notification(invoice, InvoiceStatus.EXCEPTION)
            return

        confirmed_dt = gate_result.confirmed_dt

    if skip_classify_gate and (human_locked_dt or classification_override):
        override_dt = locked_dt_code if classification_override and not human_locked_dt else human_locked_dt
        if classification_override and not human_locked_dt:
            await _log_processing_override_skip(session, invoice, "classification")
        await log_event(
            session,
            "llm_classified",
            invoice_id=invoice.id,
            detail={
                "llm_suggested_dt": override_dt,
                "llm_confidence": float(invoice.document_type_confidence or 0.95),
                "skipped": True,
                "human_locked": bool(human_locked_dt),
                "processing_override": classification_override and not human_locked_dt,
                "document_ai_provider": provider_token,
            },
        )
        await log_event(
            session,
            "classification_gate_passed",
            invoice_id=invoice.id,
            detail={
                "human_locked": bool(human_locked_dt),
                "processing_override": classification_override and not human_locked_dt,
                "confirmed_dt": override_dt,
                "confirmed_confidence": float(invoice.document_type_confidence or 0.95),
                "document_ai_provider": provider_token,
            },
        )

    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice.id)
        .options(selectinload(Invoice.line_items))
    )
    loaded = (await session.execute(stmt)).scalar_one()

    if classify_llm is not None:
        loaded.llm_suggested_dt = invoice.llm_suggested_dt
        loaded.llm_confidence = invoice.llm_confidence

    with open_pdf_for_reading(invoice.raw_file_path, tenant_id=invoice.tenant_id) as local_path:
        extract_result = await extract_fields(
            ocr,
            file_path=local_path,
            org=org,
            document_types=config.document_types,
            confirmed_dt=confirmed_dt,
            few_shots=few_shots,
            provider=doc_provider,
        )
    if extract_result.di_enrich_detail:
        await log_event(
            session,
            "di_invoice_enrich",
            invoice_id=invoice.id,
            detail=extract_result.di_enrich_detail,
        )
    llm_result = extract_result.llm
    ocr = extract_result.ocr
    if invoice.file_hash and (ocr.payload_json or {}).get("invoice_fields"):
        from app.services.classification.classification_learning_service import (
            upsert_ocr_artifact_enrichment,
        )

        await upsert_ocr_artifact_enrichment(
            session,
            tenant_id=invoice.tenant_id,
            invoice_id=invoice.id,
            file_hash=invoice.file_hash,
            ocr=ocr,
        )
    from dataclasses import replace

    from app.services.extraction.extraction_field_values import (
        apply_parsed_extraction_fields,
        effective_extraction_field_keys_for_dt,
        enrich_parsed_from_ocr,
        ensure_extraction_baseline,
        non_canonical_extraction_keys,
    )
    from app.services.extraction.field_grounding_service import ground_parsed_fields
    from app.services.extraction.gap_fill_extraction_service import apply_extraction_gap_fill
    from app.services.extraction.pdf_parser import parse_local_text

    selected_keys = effective_extraction_field_keys_for_dt(config.document_types, confirmed_dt)
    custom_keys = non_canonical_extraction_keys(selected_keys)
    dt_definition = get_document_type_definition(
        confirmed_dt,
        document_types=config.document_types,
        tenant_id=invoice.tenant_id,
    )
    citation_review_required = False
    citation_results: list = []
    if llm_result is not None:
        from app.config import get_settings as _get_settings

        _settings = _get_settings()
        if _settings.use_citation_grounding:
            from app.services.extraction.citation_grounding_service import (
                verify_and_apply_citations,
            )

            scalar_citation_keys = [
                key for key in selected_keys if str(key).strip().lower() != "line_items"
            ]
            llm_result, citation_results = verify_and_apply_citations(
                llm_result,
                ocr,
                field_keys=scalar_citation_keys,
            )
        if _settings.use_extraction_self_consistency:
            from app.services.extraction.llm_document_service import extract_document_fields
            from app.services.extraction.self_consistency_service import run_self_consistency

            llm_result, consistency_outcomes = await run_self_consistency(
                base_result=llm_result,
                ocr=ocr,
                dt_definition=dt_definition,
                extract_fn=extract_document_fields,
                extract_kwargs={
                    "ocr": ocr,
                    "org": org,
                    "document_types": config.document_types,
                    "confirmed_dt": confirmed_dt,
                    "few_shots": few_shots,
                },
                use_citation_grounding=_settings.use_citation_grounding,
            )
            disagreements = {
                key: value
                for key, value in consistency_outcomes.items()
                if not value.get("agreed")
            }
            if disagreements:
                await log_event(
                    session,
                    "self_consistency_disagreement",
                    invoice_id=invoice.id,
                    detail={"fields": disagreements},
                )
    if llm_result is not None:
        from app.services.classification.playbook_profile_catalog import (
            effective_counterparty_source,
        )

        parsed = llm_result_to_invoice_data(
            llm_result,
            ocr=ocr,
            custom_keys=custom_keys or None,
            selected_keys=selected_keys,
            org=org,
            counterparty_source=effective_counterparty_source(dt_definition)
            if dt_definition
            else "letterhead",
            route_target=dt_definition.route_target if dt_definition else None,
        )
        persist_llm_party_context(invoice, llm_result, org)
    else:
        local = parse_local_text(ocr.text or "")
        parsed = replace(local, document_text=ocr.text or local.document_text)
    parsed = ground_parsed_fields(parsed, ocr.text, selected_keys, ocr.payload_json)
    parsed = enrich_parsed_from_ocr(parsed, ocr, dt_definition=dt_definition)
    parsed, gap_fill_detail = await apply_extraction_gap_fill(
        parsed,
        ocr=ocr,
        selected_keys=selected_keys,
        org=org,
        dt_definition=dt_definition,
        invoice=loaded,
    )
    if gap_fill_detail.get("gap_fill_attempted"):
        await log_event(
            session,
            "extraction_gap_fill",
            invoice_id=invoice.id,
            detail=gap_fill_detail,
        )

    if llm_result is not None:
        from app.config import get_settings as _get_settings

        _settings = _get_settings()
        if _settings.use_citation_grounding and "line_items" in {
            str(key).strip().lower() for key in selected_keys
        }:
            from app.services.extraction.citation_grounding_service import (
                citation_audit_detail,
                verify_parsed_line_items_citation,
            )

            line_items_result = verify_parsed_line_items_citation(
                list(parsed.line_items or []),
                ocr_text=ocr.text or "",
                ocr_payload=ocr.payload_json or {},
            )
            citation_results = list(citation_results) + [line_items_result]
        if llm_result is not None and _settings.use_citation_grounding and citation_results:
            from app.services.extraction.citation_grounding_service import citation_audit_detail

            await log_event(
                session,
                "citation_grounding",
                invoice_id=invoice.id,
                detail=citation_audit_detail(citation_results),
            )
            citation_detail = citation_audit_detail(citation_results)
            if citation_detail.get("citation_failed") and flag_enabled_for_dt(
                "use_citation_grounding",
                confirmed_dt,
                tenant_id=invoice.tenant_id,
            ):
                citation_review_required = True
                loaded.evaluation_status = EVAL_NEEDS_REVIEW
                invoice.evaluation_status = EVAL_NEEDS_REVIEW
                await log_event(
                    session,
                    "routing_review_required",
                    invoice_id=invoice.id,
                    detail={
                        "gate": "citation_grounding",
                        "review_reasons": ["citation_failed"],
                        "citation_failed": citation_detail.get("citation_failed"),
                    },
                )

    field_conf_result = evaluate_field_confidence_gate(
        llm_result,
        ai_cfg=ai_cfg,
        dt_definition=dt_definition,
        parsed=parsed,
        invoice=loaded,
        confirmed_dt=confirmed_dt,
    )
    await log_event(
        session,
        "field_confidence_evaluated",
        invoice_id=invoice.id,
        detail=field_confidence_audit_detail(field_conf_result),
    )

    resolved_vendor = await _apply_parsed_to_invoice(
        session,
        invoice=invoice,
        loaded=loaded,
        parsed=parsed,
        config=config,
        preserve_existing=preserve_extracted_fields,
        org=org,
    )

    if preserve_extracted_fields:
        parsed = invoice_data_from_invoice(loaded)

    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice.id)
        .options(selectinload(Invoice.line_items))
    )
    loaded = (await session.execute(stmt)).scalar_one()

    await log_event(
        session,
        "parse_completed",
        invoice_id=invoice.id,
        detail={
            "source": provider_token,
            "confidence": "high" if not ocr.sparse else "low",
            "text_length": ocr.text_length,
            "di_model": ocr.di_model,
            "document_ai_provider": provider_token,
            "confirmed_dt": confirmed_dt,
            "extracted_snapshot": {
                "vendor": loaded.vendor,
                "invoice_no": loaded.invoice_no,
                "total": str(loaded.total) if loaded.total is not None else None,
                "subtotal": str(loaded.subtotal) if loaded.subtotal is not None else None,
                "gst": str(loaded.gst) if loaded.gst is not None else None,
                "abn": loaded.abn,
            },
        },
    )

    if human_locked_dt:
        apply_document_type_to_invoice(
            loaded,
            code=human_locked_dt,
            confidence=0.95,
            llm_suggested_dt=classify_llm.suggested_dt if classify_llm else None,
            llm_confidence=classify_llm.confidence if classify_llm else None,
        )
        await log_event(
            session,
            "document_classified",
            invoice_id=invoice.id,
            detail={
                "human_locked": True,
                "confirmed_dt": human_locked_dt,
                "llm_suggested_dt": classify_llm.suggested_dt if classify_llm else None,
                "llm_confidence": classify_llm.confidence if classify_llm else None,
                "document_ai_provider": provider_token,
                "extract_phase": True,
            },
        )
    elif gate_result is not None and gate_result.passed:
        apply_document_type_to_invoice(
            loaded,
            code=gate_result.confirmed_dt,
            confidence=gate_result.confirmed_confidence,
            llm_suggested_dt=gate_result.llm_suggested_dt,
            llm_confidence=gate_result.llm_confidence,
        )
        if llm_result is not None:
            loaded.llm_suggested_dt = llm_result.suggested_dt or gate_result.llm_suggested_dt
            loaded.llm_confidence = round(llm_result.confidence, 4)
        await log_event(
            session,
            "document_classified",
            invoice_id=invoice.id,
            detail={
                **gate_audit_detail(gate_result, provider_token=provider_token),
                "extract_phase": True,
            },
        )

    invoice.document_type_code = loaded.document_type_code
    invoice.document_type_confidence = loaded.document_type_confidence
    invoice.llm_suggested_dt = loaded.llm_suggested_dt
    invoice.llm_confidence = loaded.llm_confidence

    from app.services.invoice.invoice_post_classification_phases import apply_policy_scorer_after_extract

    await apply_policy_scorer_after_extract(
        session,
        invoice=invoice,
        loaded=loaded,
        parsed=parsed,
        config=config,
        llm_dt=(loaded.document_type_code or confirmed_dt or "").strip().upper(),
        llm_confidence=float(
            loaded.document_type_confidence
            or (gate_result.confirmed_confidence if gate_result is not None else 0.0)
        ),
    )

    await _sync_counterparty_and_evaluate(
        session,
        loaded,
        parsed=parsed,
        config=config,
        org=org,
    )
    invoice.vendor = loaded.vendor
    invoice.evaluation_status = loaded.evaluation_status
    invoice.route_target = loaded.route_target
    invoice.matched_rule_ids = loaded.matched_rule_ids
    invoice.vendor_confidence = loaded.vendor_confidence
    await _clear_purchase_awaiting_po_if_overridden(session, invoice, loaded)

    dt_definition = resolve_definition_for_invoice(loaded, list(config.document_types))
    skip_field_conf_review = False
    if dt_definition is not None:
        from app.services.classification.document_type_playbook_profile_service import effective_approval_policy

        skip_field_conf_review = effective_approval_policy(dt_definition).mode == "no_posting"

    if (
        not field_conf_result.passed
        and not bypass_review_gates
        and not skip_field_conf_review
        and not should_skip(invoice, "field_confidence")
        and not _counterparty_registration_pending(loaded)
    ):
        loaded.evaluation_status = EVAL_NEEDS_REVIEW
        invoice.evaluation_status = EVAL_NEEDS_REVIEW
        await log_event(
            session,
            "routing_review_required",
            invoice_id=invoice.id,
            detail={
                "gate": "field_confidence",
                "review_reasons": field_conf_result.review_reasons,
                "low_confidence_fields": field_conf_result.low_confidence_fields,
                "min_field_extract_confidence": field_conf_result.min_confidence,
            },
        )
    elif (
        not field_conf_result.passed
        and should_skip(invoice, "field_confidence")
    ):
        await _log_processing_override_skip(session, invoice, "field_confidence")
    elif vendor_drift_result is not None and vendor_drift_result.detected and not bypass_review_gates and not should_skip(invoice, "vendor_drift") and not _counterparty_registration_pending(loaded):
        loaded.evaluation_status = EVAL_NEEDS_REVIEW
        invoice.evaluation_status = EVAL_NEEDS_REVIEW
        await log_event(
            session,
            "routing_review_required",
            invoice_id=invoice.id,
            detail={
                "gate": "vendor_classification_drift",
                "review_reasons": vendor_drift_result.review_reasons,
                **drift_audit_detail(vendor_drift_result),
            },
        )
    elif (
        vendor_drift_result is not None
        and vendor_drift_result.detected
        and should_skip(invoice, "vendor_drift")
    ):
        await _log_processing_override_skip(session, invoice, "vendor_drift")

    from app.services.purchase.purchase_document_service import apply_purchase_document_type_after_eval

    await apply_purchase_document_type_after_eval(session, loaded)
    from app.services.sales.sales_document_service import apply_sales_document_type_after_eval

    await apply_sales_document_type_after_eval(session, loaded)

    await sync_invoice_blob_path(session, loaded, parsed_vendor=resolved_vendor)
    invoice.raw_file_path = loaded.raw_file_path
    invoice.storage_vendor_slug = loaded.storage_vendor_slug
    invoice.route_target = loaded.route_target

    parsed = ensure_extraction_baseline(loaded, parsed, ocr=ocr)
    apply_parsed_extraction_fields(loaded, parsed)
    invoice.extracted_fields = loaded.extracted_fields
    invoice.so_reference = loaded.so_reference
    invoice.document_text = loaded.document_text
    invoice.email_attachment_name = loaded.email_attachment_name

    if dt_definition is None:
        dt_definition = resolve_definition_for_invoice(loaded, list(config.document_types))

    from app.services.invoice.invoice_post_classification_phases import evaluate_playbook_with_reextract

    playbook = await evaluate_playbook_with_reextract(
        session,
        invoice=invoice,
        loaded=loaded,
        parsed=parsed,
        definition=dt_definition,
        document_types=list(config.document_types),
        ocr=ocr,
        file_path=invoice.raw_file_path,
        org=org,
        config=config,
        confirmed_dt=confirmed_dt,
        few_shots=few_shots,
        doc_provider=doc_provider,
    )
    await log_event(
        session,
        "playbook_evaluated",
        invoice_id=invoice.id,
        detail={
            **playbook.audit_detail(),
            **(
                playbook_policy_audit_detail(dt_definition)
                if dt_definition is not None
                else {}
            ),
        },
    )
    if (
        requires_playbook_review(playbook, definition=dt_definition)
        and not bypass_review_gates
        and not should_skip(invoice, "playbook")
    ):
        loaded.evaluation_status = EVAL_NEEDS_REVIEW
        invoice.evaluation_status = EVAL_NEEDS_REVIEW
        invoice.status = InvoiceStatus.EXCEPTION
        from app.services.classification.document_type_playbook_service import (
            suggest_reclassify_direct_expense_code,
        )

        suggest_dt = suggest_reclassify_direct_expense_code(
            playbook,
            dt_definition,
            list(config.document_types),
        )
        await log_event(
            session,
            "routing_review_required",
            invoice_id=invoice.id,
            detail={
                "gate": "playbook",
                "document_type_code": loaded.document_type_code,
                "document_type_confidence": loaded.document_type_confidence,
                "route_target": invoice.route_target,
                "review_reasons": (
                    gate_result.review_reasons if gate_result else []
                ),
                "playbook": playbook.audit_detail(),
                "suggest_reclassify_dt": suggest_dt,
                **(
                    playbook_policy_audit_detail(dt_definition)
                    if dt_definition is not None
                    else {}
                ),
            },
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return
    elif requires_playbook_review(playbook, definition=dt_definition) and should_skip(
        invoice, "playbook"
    ):
        await _log_processing_override_skip(session, invoice, "playbook")

    await _post_parse_relocate(session, loaded, resolved_vendor)
    invoice.raw_file_path = loaded.raw_file_path
    invoice.storage_vendor_slug = loaded.storage_vendor_slug

    if (loaded.route_target or "").strip() == ROUTE_PURCHASE:
        from app.services.purchase.purchase_document_service import sync_purchase_document

        await sync_purchase_document(session, loaded)
        invoice.purchase_document_type = loaded.purchase_document_type
        invoice.po_reference = loaded.po_reference
        invoice.evaluation_status = loaded.evaluation_status
        from app.services.invoice.invoice_post_classification_phases import log_match_phase_evaluated

        await log_match_phase_evaluated(
            session,
            invoice_id=invoice.id,
            detail={
                "route": "purchase",
                "evaluation_status": loaded.evaluation_status,
                "po_reference": loaded.po_reference,
                "purchase_document_type": loaded.purchase_document_type,
            },
        )
        if loaded.status == InvoiceStatus.EXCEPTION:
            purchase_hold_bypass = bypass_review_gates or override_bypasses_purchase_hold(invoice)
            if purchase_hold_bypass:
                from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED
                from app.services.purchase.purchase_document_service import EVAL_AWAITING_PO

                if loaded.evaluation_status == EVAL_AWAITING_PO:
                    if override_bypasses_purchase_hold(invoice) and not bypass_review_gates:
                        await _log_processing_override_skip(session, invoice, "playbook")
                    loaded.evaluation_status = EVAL_AUTO_CODED
                    invoice.evaluation_status = EVAL_AUTO_CODED
                loaded.status = InvoiceStatus.PARSING
                invoice.status = InvoiceStatus.PARSING
            else:
                invoice.status = InvoiceStatus.EXCEPTION
                return

    if (loaded.route_target or "").strip() == ROUTE_SALES:
        from app.services.sales.sales_document_service import EVAL_AWAITING_SO, sync_sales_document

        await sync_sales_document(session, loaded)
        invoice.sales_document_type = loaded.sales_document_type
        invoice.so_reference = loaded.so_reference
        invoice.evaluation_status = loaded.evaluation_status
        from app.services.invoice.invoice_post_classification_phases import log_match_phase_evaluated

        await log_match_phase_evaluated(
            session,
            invoice_id=invoice.id,
            detail={
                "route": "sales",
                "evaluation_status": loaded.evaluation_status,
                "so_reference": loaded.so_reference,
                "sales_document_type": loaded.sales_document_type,
            },
        )
        if loaded.status == InvoiceStatus.EXCEPTION:
            sales_hold_bypass = bypass_review_gates
            if sales_hold_bypass:
                from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED

                if loaded.evaluation_status == EVAL_AWAITING_SO:
                    loaded.evaluation_status = EVAL_AUTO_CODED
                    invoice.evaluation_status = EVAL_AUTO_CODED
                loaded.status = InvoiceStatus.PARSING
                invoice.status = InvoiceStatus.PARSING
            else:
                invoice.status = InvoiceStatus.EXCEPTION
                return

    if await _vendor_hold_unless_skipped(session, loaded):
        invoice.status = InvoiceStatus.EXCEPTION
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    invoice.status = InvoiceStatus.VALIDATING
    await session.flush()
    doc_type = loaded.purchase_document_type
    from app.services.classification.document_type_validation_service import PROFILE_STANDARD

    validation_profile = (
        PROFILE_STANDARD
        if not (loaded.document_type_code or "").strip()
        else None
    )
    results = await run_all_validations(
        parsed,
        session,
        invoice.id,
        tenant_id=invoice.tenant_id,
        sender=invoice.email_sender,
        route_target=invoice.route_target,
        purchase_document_type=doc_type,
        has_receipt_file=has_receipt_attachment(invoice.raw_file_path),
        document_type_code=loaded.document_type_code,
        document_types=list(config.document_types),
        validation_profile=validation_profile,
        playbook_gates=playbook,
        invoice=loaded,
    )
    invoice.validation_results = results_to_json(results)
    invoice.abn = parsed.abn
    if not all_passed(results):
        if bypass_review_gates and human_approval_may_bypass_validation(results):
            await log_event(
                session,
                "validation_bypassed_after_human_approval",
                invoice_id=invoice.id,
                detail=validation_audit_detail(
                    results,
                    route_target=invoice.route_target,
                    has_receipt_file=has_receipt_attachment(invoice.raw_file_path),
                ),
            )
        elif should_skip(invoice, "validation"):
            await _log_processing_override_skip(session, invoice, "validation")
            await log_event(
                session,
                "validation_bypassed_processing_override",
                invoice_id=invoice.id,
                detail=validation_audit_detail(
                    results,
                    route_target=invoice.route_target,
                    has_receipt_file=has_receipt_attachment(invoice.raw_file_path),
                ),
            )
        else:
            stmt = (
                select(Invoice)
                .where(Invoice.id == invoice.id)
                .options(selectinload(Invoice.line_items))
            )
            loaded = (await session.execute(stmt)).scalar_one()
            await _sync_counterparty_and_evaluate(
                session,
                loaded,
                parsed=parsed,
                config=config,
                org=org,
            )
            await sync_invoice_blob_path(session, loaded, parsed_vendor=resolved_vendor)
            invoice.raw_file_path = loaded.raw_file_path
            invoice.route_target = loaded.route_target
            if await _vendor_hold_unless_skipped(session, loaded):
                invoice.status = InvoiceStatus.EXCEPTION
                send_notification(invoice, InvoiceStatus.EXCEPTION)
                return
            invoice.status = InvoiceStatus.EXCEPTION
            await log_event(
                session,
                "validation_failed",
                invoice_id=invoice.id,
                detail=validation_audit_detail(
                    results,
                    route_target=invoice.route_target,
                    has_receipt_file=has_receipt_attachment(invoice.raw_file_path),
                ),
            )
            send_notification(invoice, InvoiceStatus.EXCEPTION)
            return

    await log_event(
        session,
        "validation_passed",
        invoice_id=invoice.id,
        detail=validation_audit_detail(
            results,
            route_target=invoice.route_target,
            has_receipt_file=has_receipt_attachment(invoice.raw_file_path),
        ),
    )

    if await apply_document_type_approval_gate(
        session,
        invoice,
        definition=dt_definition,
        validation_results=results,
        human_approval_bypass=bypass_review_gates,
    ):
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    if (invoice.route_target or "").strip() == ROUTE_VAULT:
        _mark_invoice_processed(invoice)
        if not citation_review_required:
            invoice.evaluation_status = EVAL_STATUS_AUTO_CODED
            loaded.evaluation_status = EVAL_STATUS_AUTO_CODED
        await log_event(
            session,
            "vault_stored",
            invoice_id=invoice.id,
            detail={
                "document_type_code": loaded.document_type_code,
                "route_target": invoice.route_target,
            },
        )
        send_notification(invoice, InvoiceStatus.PROCESSED)
        return

    if doc_type in ("po", "grn") and not bypass_review_gates:
        await _finish_purchase_supporting_document(session, invoice)
        return

    sales_doc_type = (loaded.sales_document_type or invoice.sales_document_type or "").strip().lower()
    if (
        sales_doc_type in ("so", "dn")
        and (invoice.route_target or "").strip() == ROUTE_SALES
        and not bypass_review_gates
    ):
        await _finish_sales_supporting_document(session, invoice)
        return

    from app.services.classification.document_type_playbook_profile_service import allows_posting_pipeline
    from app.services.invoice.non_posting_document_service import finish_non_posting_document

    if dt_definition is not None and not allows_posting_pipeline(dt_definition):
        await finish_non_posting_document(
            session,
            invoice,
            definition=dt_definition,
            detail={
                "document_type_code": loaded.document_type_code,
                "route_target": invoice.route_target,
            },
        )
        await _safe_auto_learn(session, invoice)
        return

    post_validate = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    if await _vendor_hold_unless_skipped(session, post_validate):
        invoice.status = InvoiceStatus.EXCEPTION
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    invoice.status = InvoiceStatus.MAPPING
    await session.flush()
    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice.id)
        .options(selectinload(Invoice.line_items))
    )
    loaded = (await session.execute(stmt)).scalar_one()
    from app.services.purchase.purchase_match_service import load_purchase_order_for_invoice
    from app.services.sales.sales_match_service import load_sales_order_for_invoice

    linked_po = await load_purchase_order_for_invoice(session, loaded)
    linked_so = await load_sales_order_for_invoice(session, loaded)
    map_config = await load_config_for_tenant(session, loaded.tenant_id)
    mapping, mapping_detail = _resolve_header_mapping(
        loaded,
        config=map_config,
        purchase_order=linked_po,
        sales_order=linked_so,
    )
    invoice.account_code = mapping.account_code
    invoice.account_name = mapping.account_name
    await _sync_counterparty_and_evaluate(
        session,
        loaded,
        parsed=parsed,
        config=config,
        org=org,
    )
    await sync_invoice_blob_path(session, loaded, parsed_vendor=resolved_vendor)
    invoice.raw_file_path = loaded.raw_file_path
    invoice.route_target = loaded.route_target
    if await _vendor_hold_unless_skipped(session, loaded):
        invoice.status = InvoiceStatus.EXCEPTION
        invoice.evaluation_status = loaded.evaluation_status
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return
    await log_event(
        session,
        "mapping_applied",
        invoice_id=invoice.id,
        detail={
            "account_code": mapping.account_code,
            "account_name": mapping.account_name,
            "rule_type": mapping_detail.rule_type,
            "match_reason": mapping_detail.match_reason,
        },
    )

    if not should_skip(invoice, "line_gl_mapping"):
        from app.services.classification.line_gl_mapping_service import apply_line_gl_mapping

        await apply_line_gl_mapping(session, loaded, map_config)
    else:
        await _log_processing_override_skip(session, invoice, "line_gl_mapping")

    if requires_gl_mapping_review(
        loaded,
        mapping_detail,
        document_types=list(config.document_types),
    ) and not bypass_review_gates and not should_skip(invoice, "mapping_review"):
        invoice.status = InvoiceStatus.EXCEPTION
        invoice.evaluation_status = EVAL_NEEDS_REVIEW
        await log_event(
            session,
            "mapping_review_required",
            invoice_id=invoice.id,
            detail={
                "document_type_code": loaded.document_type_code,
                "route_target": invoice.route_target,
                "account_name": mapping.account_name,
                "rule_type": mapping_detail.rule_type,
                "match_reason": mapping_detail.match_reason,
            },
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return
    elif requires_gl_mapping_review(
        loaded,
        mapping_detail,
        document_types=list(config.document_types),
    ) and should_skip(invoice, "mapping_review"):
        await _log_processing_override_skip(session, invoice, "mapping_review")

    from app.services.rule_book.rule_book_mapper import ROUTE_EXPENSES

    if (invoice.route_target or "").strip() == ROUTE_EXPENSES and is_staff_claim_sender(
        invoice.email_sender,
        config.employee_masters,
    ):
        await log_event(
            session,
            "staff_claim_guard_triggered",
            invoice_id=invoice.id,
            detail={
                "channel": infer_capture_channel(invoice.email_sender),
                **audit_document_detail(invoice),
                "reason": "mobile channel — bypassed expense rules",
            },
        )

    if await apply_team_expense_approval_gate(session, invoice):
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    invoice.status = InvoiceStatus.JOURNALING
    await session.flush()
    existing_entries = (
        await session.execute(
            select(JournalEntry).where(
                *journal_entries_for_invoice(invoice.tenant_id, invoice.id),
            )
        )
    ).scalars().all()
    for entry in existing_entries:
        await session.delete(entry)
    await session.flush()
    journal_lines = generate_entries(invoice, mapping, config=config, sales_order=linked_so)
    if not is_balanced(journal_lines):
        invoice.status = InvoiceStatus.EXCEPTION
        await log_event(
            session,
            "journal_unbalanced",
            invoice_id=invoice.id,
            detail={
                "subtotal": float(invoice.subtotal or 0),
                "gst": float(invoice.gst or 0),
                "total": float(invoice.total or 0),
            },
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return
    for line in journal_lines:
        session.add(
            JournalEntry(
                tenant_id=invoice.tenant_id,
                invoice_id=invoice.id,
                date=line.date,
                account_code=line.account_code,
                account_name=line.account_name,
                debit=line.debit,
                credit=line.credit,
                entry_type=line.entry_type,
            )
        )

    invoice.status = InvoiceStatus.RECONCILING
    await session.flush()
    recon_date = invoice.invoice_date or date.today()
    recon = await reconcile_daily(
        session,
        recon_date,
        tenant_id=invoice.tenant_id,
        current_invoice=invoice,
        config=config,
    )
    await save_reconciliation(session, recon, tenant_id=invoice.tenant_id)
    if recon.halted:
        route = (invoice.route_target or "").strip()
        non_blocking_recon = route in (ROUTE_TEAM, ROUTE_EXPENSES, ROUTE_SALES) or bypass_review_gates
        if non_blocking_recon:
            await log_event(
                session,
                "reconciliation_skipped",
                invoice_id=invoice.id,
                detail={"reason": recon.halt_reason, "route_target": route},
            )
        else:
            invoice.status = InvoiceStatus.EXCEPTION
            await log_event(
                session,
                "reconciliation_halted",
                invoice_id=invoice.id,
                detail={"reason": recon.halt_reason},
            )
            send_notification(invoice, InvoiceStatus.EXCEPTION)
            return

    pre_post = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    if await _vendor_hold_unless_skipped(session, pre_post):
        invoice.status = InvoiceStatus.EXCEPTION
        invoice.evaluation_status = pre_post.evaluation_status
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    _mark_invoice_processed(invoice)
    await session.flush()
    await record_team_expense_processed(session, invoice)
    from app.services.purchase.purchase_document_service import (
        is_commercial_purchase_invoice,
        sync_purchase_document,
    )

    await sync_purchase_document(session, invoice)
    if invoice.evaluation_status == "awaiting_po":
        if bypass_review_gates or override_bypasses_purchase_hold(invoice):
            from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED

            if override_bypasses_purchase_hold(invoice) and not bypass_review_gates:
                await _log_processing_override_skip(session, invoice, "playbook")
            invoice.evaluation_status = EVAL_AUTO_CODED
        else:
            invoice.status = InvoiceStatus.EXCEPTION
            await session.flush()
            send_notification(invoice, InvoiceStatus.EXCEPTION)
            return
    if is_commercial_purchase_invoice(invoice):
        from app.services.payments.settlement_service import ensure_payment_with_audit

        await ensure_payment_with_audit(session, invoice)

    from app.services.sales.sales_document_service import (
        is_commercial_sales_invoice,
        sync_sales_document,
    )

    await sync_sales_document(session, invoice)
    if is_commercial_sales_invoice(invoice):
        from app.services.payments.settlement_service import ensure_receivable_with_audit

        await ensure_receivable_with_audit(session, invoice)
    await _safe_auto_learn(session, invoice)
    await log_event(
        session,
        "invoice_processed",
        invoice_id=invoice.id,
        detail={
            "route_target": invoice.route_target,
            "status": invoice.status.value,
            "vendor": invoice.vendor,
            "amount": float(invoice.total) if invoice.total is not None else None,
        },
    )
    from app.services.integration.publish_service import publish_invoice_to_ledger

    await publish_invoice_to_ledger(
        session,
        invoice,
        auto=True,
        skip_if_insufficient_credits=True,
    )
    send_notification(invoice, InvoiceStatus.PROCESSED)
