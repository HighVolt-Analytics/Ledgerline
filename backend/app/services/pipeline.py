"""Run the invoice processing pipeline for one PDF."""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.services.amount_sanity import plausible_money
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.models.journal import JournalEntry
from app.models.line_item import LineItem
from app.models.vendor import VendorRegistry
from app.services.account_mapper import AccountMapping, MappingDetail
from app.services.document_duplicate_service import (
    create_duplicate_shadow_invoice,
    evaluate_file_hash_duplicate,
    find_invoice_by_file_hash,
    log_duplicate_in_progress,
)
from app.services.document_ref_service import assign_document_ref, audit_document_detail
from app.services.ingest_capture_service import apply_ingest_capture, evaluate_ingest_capture
from app.services.approval_pipeline_service import human_approved_payable_bypass
from app.services.ingest_fanout_service import IngestSourceMetadata, ingest_file_with_fanout
from app.services.invoice_reset import reset_invoice_for_reprocess
from app.services.invoice_evaluation_service import (
    EVAL_AWAITING_CLASSIFICATION,
    EVAL_NEEDS_RESCAN,
    EVAL_NEEDS_REVIEW,
    ROUTE_EXPENSES,
    ROUTE_PURCHASE,
    ROUTE_TEAM,
    ROUTE_VAULT,
    apply_invoice_evaluation,
    load_config_for_tenant,
)
from app.services.routing_review_service import (
    requires_gl_mapping_review,
    requires_playbook_review,
)
from app.services.classification_learning_service import (
    few_shot_examples_for_tenant,
    human_confirmed_document_type,
    resolve_vendor_learning_key,
)
from app.services.classification_drift_service import (
    check_vendor_classification_drift,
    drift_audit_detail,
)
from app.services.di_extract_service import OcrFailed
from app.services.document_ai_provider import (
    DocumentAiProvider,
    extract_fields,
)
from app.services.invoice_pipeline_phases import (
    apply_user_defined_classifier_gate,
    evaluate_confidence_gate,
    evaluate_field_confidence_gate,
    evaluate_image_quality_gate,
    field_confidence_audit_detail,
    gate_audit_detail,
    image_quality_audit_detail,
    phase_llm_classify,
    phase_ocr,
    phase_storage_verify,
)
from app.services.llm_document_service import (
    apply_document_type_to_invoice,
    llm_result_to_invoice_data,
)
from app.schemas.classification_decision import ReviewReason
from app.services.tenant_org_context import ai_classification_from_config
from app.schemas.llm_document import LlmDocumentResult
from app.services.tenant_org_context import org_context_from_config
from app.services.vault_paths import filename_from_stored
from app.services.document_type_catalog import get_document_type_definition
from app.services.document_type_playbook_service import (
    evaluate_playbook_gates,
    resolve_definition_for_invoice,
)
from app.services.document_type_approval_service import apply_document_type_approval_gate
from app.services.document_type_playbook_profile_service import playbook_policy_audit_detail
from app.services.rule_book_mapper import is_fallback_mapping, map_invoice_with_details
from app.services.team_expense_approval import apply_team_expense_approval_gate
from app.services.team_expense_service import record_team_expense_processed
from app.services.team_expense_validator import has_receipt_attachment
from app.services.vendor_hold_service import apply_vendor_hold_if_needed
from app.services.bundle_vendor_service import reconcile_dossier_vendor, resolve_canonical_vendor_name
from app.services.vendor_name_utils import is_plausible_vendor_name
from app.services.invoice_data import InvoiceData, ParsedLineItem
from app.tenant_child_tables import journal_entries_for_invoice, line_items_for_invoice
from app.services.attachment_filter import filter_invoice_attachments
from app.services.audit_detail_helpers import validation_audit_detail
from app.services.audit_service import log_event
from app.services.capture_channel import infer_capture_channel, is_staff_claim_sender
from app.services.email_ingestion import RawEmail, mark_message_read
from app.services.file_storage import open_pdf_for_reading
from app.services.vault_blob_sync import sync_invoice_blob_path
from app.services.graph_mail_folders import folder_moves_enabled
from app.services.journal_generator import generate_entries
from app.services.notifier import send_notification
from app.services.reconciliation_service import reconcile_daily, save_reconciliation
from app.services.validator import all_passed, results_to_json, run_all_validations
from app.services.vendor_resolver import (
    UNKNOWN_SLUG,
    is_valid_storage_slug,
    resolve_storage_slug_for_parsed_vendor,
    resolve_vendor_slug,
)
from app.utils.hashing import compute_sha256_bytes


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
    await session.execute(
        delete(LineItem).where(
            *line_items_for_invoice(invoice.tenant_id, invoice.id),
        )
    )
    await session.flush()
    for line in lines:
        session.add(
            LineItem(
                tenant_id=invoice.tenant_id,
                invoice_id=invoice.id,
                description=line.description,
                qty=line.qty,
                unit_price=line.unit_price,
                amount=line.amount,
                tax_amount=line.tax_amount,
            )
        )


def _resolve_header_mapping(
    invoice: Invoice,
    *,
    config,
    purchase_order=None,
) -> tuple[AccountMapping, MappingDetail]:
    """Map invoice header using unified classification config."""
    if not invoice.line_items:
        detail = map_invoice_with_details(invoice, config=config, purchase_order=purchase_order)
        return (
            AccountMapping(
                account_code=detail.account_code,
                account_name=detail.account_name,
                expense_category=detail.expense_category,
            ),
            detail,
        )
    best_detail = map_invoice_with_details(invoice, config=config, purchase_order=purchase_order)
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

        for att in attachments:
            capture_rule = evaluate_ingest_capture(email, att, capture_config)
            if not capture_rule:
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
            existing = await find_invoice_by_file_hash(session, file_hash, tenant_id=tenant_id)
            duplicate_decision = evaluate_file_hash_duplicate(existing)
            if duplicate_decision.action == "skip_in_progress":
                assert existing is not None
                existing.email_message_id = email.message_id
                await log_duplicate_in_progress(
                    session,
                    existing,
                    detail={
                        "filename": att.filename,
                        "message_id": email.message_id,
                        "mailbox": email.mailbox_email,
                        "source": "email",
                    },
                )
                continue
            if duplicate_decision.action == "skip_logged":
                assert existing is not None
                existing.email_message_id = email.message_id
                await log_event(
                    session,
                    "duplicate_skipped",
                    invoice_id=existing.id,
                    detail={
                        "filename": att.filename,
                        "message_id": email.message_id,
                        "source": "email",
                        "note": "repeat submission ignored",
                    },
                )
                continue
            if duplicate_decision.action == "shadow_duplicate":
                assert existing is not None
                await create_duplicate_shadow_invoice(
                    session,
                    tenant_id=tenant_id,
                    original=existing,
                    connected_mailbox_id=connected_mailbox_id,
                    email_sender=email.sender or None,
                    email_subject=email.subject or None,
                    email_attachment_name=att.filename,
                    email_message_id=email.message_id,
                    capture_source="email",
                    file_hash=file_hash,
                    extra_detail={
                        "filename": att.filename,
                        "message_id": email.message_id,
                        "mailbox": email.mailbox_email,
                        "source": "email",
                    },
                )
                continue
            if duplicate_decision.action == "reingest_rejected":
                assert existing is not None
                existing.email_sender = email.sender or None
                existing.email_subject = email.subject or None
                existing.email_attachment_name = att.filename
                existing.email_message_id = email.message_id
                await reset_invoice_for_reprocess(session, existing)
                await apply_ingest_capture(session, existing, email, att)
                await log_event(
                    session,
                    "duplicate_reingest_rejected",
                    invoice_id=existing.id,
                    detail={
                        "filename": att.filename,
                        "message_id": email.message_id,
                        "source": "email",
                    },
                )
                result.ingested_count += 1
                continue

            vendor_slug = await resolve_vendor_slug(
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

        _maybe_finish_email_message(
            email,
            mark_processed=mark_processed,
            mark_processed_only_if_ingested=mark_processed_only_if_ingested,
            ingested_before=ingested_before,
            ingested_after=result.ingested_count,
        )

    return result


async def _finish_purchase_supporting_document(session: AsyncSession, invoice: Invoice) -> None:
    """PO / GRN documents: map, sync register, skip AP journal and payment."""
    from app.services.purchase_match_service import load_purchase_order_for_invoice
    from app.services.purchase_document_service import EVAL_AWAITING_PO, sync_purchase_document

    loaded = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    linked_po = await load_purchase_order_for_invoice(session, loaded)
    map_config = await load_config_for_tenant(session, loaded.tenant_id)
    mapping, mapping_detail = _resolve_header_mapping(
        loaded,
        config=map_config,
        purchase_order=linked_po,
    )
    invoice.account_code = mapping.account_code
    invoice.account_name = mapping.account_name
    await apply_invoice_evaluation(session, loaded)
    await sync_invoice_blob_path(session, loaded, parsed_vendor=loaded.vendor)
    invoice.raw_file_path = loaded.raw_file_path
    invoice.route_target = loaded.route_target
    await log_event(
        session,
        "mapping_applied",
        invoice_id=invoice.id,
        detail={
            "account_code": mapping.account_code,
            "account_name": mapping.account_name,
            "rule_type": mapping_detail.rule_type,
            "match_reason": mapping_detail.match_reason,
            "purchase_document_type": invoice.purchase_document_type,
        },
    )

    await sync_purchase_document(session, invoice)
    if invoice.evaluation_status == EVAL_AWAITING_PO:
        invoice.status = InvoiceStatus.EXCEPTION
        await session.flush()
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    from app.services.invoice_evaluation_service import EVAL_AUTO_CODED

    if linked_po:
        await reconcile_dossier_vendor(
            session,
            invoice,
            linked_po,
            document_type=invoice.purchase_document_type,
        )
    invoice.evaluation_status = EVAL_AUTO_CODED

    invoice.status = InvoiceStatus.PROCESSED
    await session.flush()
    await _auto_learn_sender(session, invoice)
    await log_event(
        session,
        "purchase_document_processed",
        invoice_id=invoice.id,
        detail={"purchase_document_type": invoice.purchase_document_type},
    )
    send_notification(invoice, InvoiceStatus.PROCESSED)


async def _apply_parsed_to_invoice(
    session: AsyncSession,
    *,
    invoice: Invoice,
    loaded: Invoice,
    parsed: InvoiceData,
    config,
) -> str | None:
    """Write extracted AP fields onto invoice rows (post-classification extract phase)."""
    resolved_vendor = resolve_canonical_vendor_name(
        invoice.tenant_id,
        vendor_names=[parsed.vendor],
        abns=[parsed.abn],
        config=config,
    )
    if not resolved_vendor and parsed.vendor and is_plausible_vendor_name(parsed.vendor):
        resolved_vendor = parsed.vendor

    from app.utils.abn_validator import storage_abn

    invoice.vendor = resolved_vendor
    invoice.abn = storage_abn(parsed.abn)
    parsed.abn = invoice.abn
    invoice.billing_address = parsed.billing_address
    invoice.bank_bsb = parsed.bank_bsb
    invoice.bank_account = parsed.bank_account
    invoice.invoice_no = parsed.invoice_no
    invoice.po_reference = parsed.po_reference
    invoice.cost_centre = parsed.cost_centre
    invoice.invoice_date = parsed.invoice_date
    invoice.due_date = parsed.due_date
    invoice.subtotal = plausible_money(parsed.subtotal)
    invoice.gst = plausible_money(parsed.gst)
    invoice.total = plausible_money(parsed.total)
    invoice.currency = parsed.currency
    from app.services.document_text import cap_document_text
    from app.services.po_reference import effective_po_reference, extract_po_reference_from_text

    invoice.document_text = cap_document_text(parsed.document_text)
    from app.services.extraction_field_values import apply_parsed_extraction_fields

    apply_parsed_extraction_fields(invoice, parsed)
    if not effective_po_reference(invoice.po_reference):
        extracted = extract_po_reference_from_text(invoice.document_text)
        if extracted:
            invoice.po_reference = extracted
            parsed.po_reference = extracted

    loaded.vendor = invoice.vendor
    loaded.abn = invoice.abn
    loaded.billing_address = invoice.billing_address
    loaded.bank_bsb = invoice.bank_bsb
    loaded.bank_account = invoice.bank_account
    loaded.invoice_no = invoice.invoice_no
    loaded.po_reference = invoice.po_reference
    loaded.cost_centre = invoice.cost_centre
    loaded.invoice_date = invoice.invoice_date
    loaded.due_date = invoice.due_date
    loaded.subtotal = invoice.subtotal
    loaded.gst = invoice.gst
    loaded.total = invoice.total
    loaded.currency = invoice.currency
    loaded.document_text = invoice.document_text
    loaded.document_heading = invoice.document_heading
    loaded.extracted_fields = invoice.extracted_fields

    await _replace_line_items(session, loaded, parsed.line_items)
    return resolved_vendor


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
    except OcrFailed:
        invoice.status = InvoiceStatus.EXCEPTION
        await log_event(
            session,
            "parsing_failed",
            invoice_id=invoice.id,
            detail=audit_document_detail(
                invoice,
                reason="stored_file_missing",
                path=invoice.raw_file_path,
            ),
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    skip_classify_gate = bool(human_locked_dt)
    classify_llm: LlmDocumentResult | None = None
    gate_result = None
    vendor_drift_result = None
    confirmed_dt = human_locked_dt or ""

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
            invoice.status = InvoiceStatus.EXCEPTION
            await log_event(
                session,
                "routing_review_required",
                invoice_id=invoice.id,
                detail={
                    "gate": "classification",
                    "document_type_code": None,
                    "document_type_confidence": None,
                    "route_target": None,
                    "review_reasons": gate_result.review_reasons,
                    "llm_suggested_dt": gate_result.llm_suggested_dt,
                    "llm_confidence": gate_result.llm_confidence,
                    "document_ai_provider": provider_token,
                },
            )
            send_notification(invoice, InvoiceStatus.EXCEPTION)
            return

        confirmed_dt = gate_result.confirmed_dt

    if skip_classify_gate and human_locked_dt:
        await log_event(
            session,
            "classification_gate_passed",
            invoice_id=invoice.id,
            detail={
                "human_locked": True,
                "confirmed_dt": human_locked_dt,
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

    extract_llm = await extract_fields(
        ocr,
        file_path=invoice.raw_file_path,
        org=org,
        document_types=config.document_types,
        confirmed_dt=confirmed_dt,
        few_shots=few_shots,
        provider=doc_provider,
    )
    llm_result = extract_llm
    field_conf_result = evaluate_field_confidence_gate(llm_result, ai_cfg=ai_cfg)
    await log_event(
        session,
        "field_confidence_evaluated",
        invoice_id=invoice.id,
        detail=field_confidence_audit_detail(field_conf_result),
    )
    from dataclasses import replace

    from app.services.extraction_field_values import (
        custom_extraction_field_keys_for_dt,
        enrich_parsed_from_ocr,
    )
    from app.services.pdf_parser import parse_local_text

    custom_keys = custom_extraction_field_keys_for_dt(config.document_types, confirmed_dt)
    if llm_result is not None:
        parsed = llm_result_to_invoice_data(
            llm_result,
            ocr=ocr,
            custom_keys=custom_keys or None,
        )
    else:
        local = parse_local_text(ocr.text or "")
        parsed = replace(local, document_text=ocr.text or local.document_text)
    parsed = enrich_parsed_from_ocr(parsed, ocr)

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
        },
    )

    resolved_vendor = await _apply_parsed_to_invoice(
        session,
        invoice=invoice,
        loaded=loaded,
        parsed=parsed,
        config=config,
    )

    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice.id)
        .options(selectinload(Invoice.line_items))
    )
    loaded = (await session.execute(stmt)).scalar_one()

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

    await apply_invoice_evaluation(session, loaded, config=config)
    invoice.evaluation_status = loaded.evaluation_status
    invoice.route_target = loaded.route_target
    invoice.matched_rule_ids = loaded.matched_rule_ids
    invoice.vendor_confidence = loaded.vendor_confidence
    if not field_conf_result.passed:
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
    elif vendor_drift_result is not None and vendor_drift_result.detected:
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

    from app.services.purchase_document_service import apply_purchase_document_type_after_eval

    await apply_purchase_document_type_after_eval(session, loaded)

    await sync_invoice_blob_path(session, loaded, parsed_vendor=resolved_vendor)
    invoice.raw_file_path = loaded.raw_file_path
    invoice.storage_vendor_slug = loaded.storage_vendor_slug
    invoice.route_target = loaded.route_target

    dt_definition = resolve_definition_for_invoice(loaded, list(config.document_types))

    playbook = await evaluate_playbook_gates(
        session,
        invoice=loaded,
        parsed=parsed,
        definition=dt_definition,
        document_types=list(config.document_types),
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
    if requires_playbook_review(playbook, definition=dt_definition) and not bypass_review_gates:
        loaded.evaluation_status = EVAL_NEEDS_REVIEW
        invoice.evaluation_status = EVAL_NEEDS_REVIEW
        invoice.status = InvoiceStatus.EXCEPTION
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
                **(
                    playbook_policy_audit_detail(dt_definition)
                    if dt_definition is not None
                    else {}
                ),
            },
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    await _post_parse_relocate(session, loaded, resolved_vendor)
    invoice.raw_file_path = loaded.raw_file_path
    invoice.storage_vendor_slug = loaded.storage_vendor_slug

    if (loaded.route_target or "").strip() == ROUTE_PURCHASE:
        from app.services.purchase_document_service import sync_purchase_document

        await sync_purchase_document(session, loaded)
        invoice.purchase_document_type = loaded.purchase_document_type
        invoice.po_reference = loaded.po_reference
        invoice.evaluation_status = loaded.evaluation_status
        if loaded.status == InvoiceStatus.EXCEPTION:
            if bypass_review_gates:
                from app.services.invoice_evaluation_service import EVAL_AUTO_CODED

                loaded.evaluation_status = EVAL_AUTO_CODED
                invoice.evaluation_status = EVAL_AUTO_CODED
                loaded.status = InvoiceStatus.PARSING
                invoice.status = InvoiceStatus.PARSING
            else:
                invoice.status = InvoiceStatus.EXCEPTION
                return

    if await apply_vendor_hold_if_needed(session, loaded) and not bypass_review_gates:
        invoice.status = InvoiceStatus.EXCEPTION
        return

    invoice.status = InvoiceStatus.VALIDATING
    await session.flush()
    doc_type = loaded.purchase_document_type
    from app.services.document_type_validation_service import PROFILE_STANDARD

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
        if bypass_review_gates:
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
        else:
            stmt = (
                select(Invoice)
                .where(Invoice.id == invoice.id)
                .options(selectinload(Invoice.line_items))
            )
            loaded = (await session.execute(stmt)).scalar_one()
            await apply_invoice_evaluation(session, loaded)
            await sync_invoice_blob_path(session, loaded, parsed_vendor=resolved_vendor)
            invoice.raw_file_path = loaded.raw_file_path
            invoice.route_target = loaded.route_target
            if await apply_vendor_hold_if_needed(session, loaded):
                invoice.status = InvoiceStatus.EXCEPTION
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
    ):
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    if (invoice.route_target or "").strip() == ROUTE_VAULT:
        invoice.status = InvoiceStatus.PROCESSED
        invoice.evaluation_status = "needs_review"
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

    post_validate = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    if await apply_vendor_hold_if_needed(session, post_validate) and not bypass_review_gates:
        invoice.status = InvoiceStatus.EXCEPTION
        return

    invoice.status = InvoiceStatus.MAPPING
    await session.flush()
    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice.id)
        .options(selectinload(Invoice.line_items))
    )
    loaded = (await session.execute(stmt)).scalar_one()
    from app.services.purchase_match_service import load_purchase_order_for_invoice

    linked_po = await load_purchase_order_for_invoice(session, loaded)
    map_config = await load_config_for_tenant(session, loaded.tenant_id)
    mapping, mapping_detail = _resolve_header_mapping(
        loaded,
        config=map_config,
        purchase_order=linked_po,
    )
    invoice.account_code = mapping.account_code
    invoice.account_name = mapping.account_name
    await apply_invoice_evaluation(session, loaded)
    await sync_invoice_blob_path(session, loaded, parsed_vendor=resolved_vendor)
    invoice.raw_file_path = loaded.raw_file_path
    invoice.route_target = loaded.route_target
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

    if requires_gl_mapping_review(
        loaded,
        mapping_detail,
        document_types=list(config.document_types),
    ) and not bypass_review_gates:
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

    from app.services.rule_book_mapper import ROUTE_EXPENSES

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
    for line in generate_entries(invoice, mapping, config=config):
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
        session, recon_date, tenant_id=invoice.tenant_id, current_invoice=invoice
    )
    await save_reconciliation(session, recon, tenant_id=invoice.tenant_id)
    if recon.halted:
        route = (invoice.route_target or "").strip()
        non_blocking_recon = route in (ROUTE_TEAM, ROUTE_EXPENSES) or bypass_review_gates
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

    invoice.status = InvoiceStatus.PROCESSED
    await session.flush()
    await record_team_expense_processed(session, invoice)
    from app.services.payment_service import ensure_payment_for_invoice
    from app.services.purchase_document_service import (
        is_commercial_purchase_invoice,
        sync_purchase_document,
    )

    await sync_purchase_document(session, invoice)
    if invoice.evaluation_status == "awaiting_po":
        if bypass_review_gates:
            from app.services.invoice_evaluation_service import EVAL_AUTO_CODED

            invoice.evaluation_status = EVAL_AUTO_CODED
        else:
            invoice.status = InvoiceStatus.EXCEPTION
            await session.flush()
            send_notification(invoice, InvoiceStatus.EXCEPTION)
            return
    if is_commercial_purchase_invoice(invoice):
        await ensure_payment_for_invoice(session, invoice)
    await _auto_learn_sender(session, invoice)
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
    from app.services.publish_service import publish_invoice_to_ledger

    await publish_invoice_to_ledger(
        session,
        invoice,
        auto=True,
        skip_if_insufficient_credits=True,
    )
    send_notification(invoice, InvoiceStatus.PROCESSED)
