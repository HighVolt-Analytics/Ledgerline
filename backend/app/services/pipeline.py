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
from app.services.invoice_reset import reset_invoice_for_reprocess
from app.services.invoice_evaluation_service import (
    EVAL_NEEDS_REVIEW,
    ROUTE_EXPENSES,
    ROUTE_PURCHASE,
    ROUTE_TEAM,
    ROUTE_VAULT,
    apply_invoice_evaluation,
    load_config_for_tenant,
)
from app.services.segment_heading_classification import (
    list_heading_aware_document_type_matches,
    load_segment_heading_kind_from_audit,
)
from app.services.vault_paths import filename_from_stored
from app.services.routing_review_service import (
    requires_classification_review,
    requires_gl_mapping_review,
    requires_playbook_review,
)
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
from app.services.invoice_data import ParsedLineItem
from app.tenant_child_tables import journal_entries_for_invoice, line_items_for_invoice
from app.services.attachment_filter import filter_invoice_attachments
from app.services.audit_detail_helpers import validation_audit_detail
from app.services.audit_service import log_event
from app.services.capture_channel import infer_capture_channel, is_staff_claim_sender
from app.services.document_type_classifier import (
    apply_document_type_classification,
    classification_audit_detail,
    classify_document_type,
)
from app.services.email_ingestion import RawEmail, mark_message_read
from app.services.file_storage import (
    open_pdf_for_reading,
    repair_invoice_stored_path,
    store_invoice_pdf,
    stored_file_available,
)
from app.services.vault_blob_sync import sync_invoice_blob_path
from app.services.graph_mail_folders import folder_moves_enabled
from app.services.journal_generator import generate_entries
from app.services.notifier import send_notification
from app.services.pdf_parser import parse_invoice
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
            inv = Invoice(
                tenant_id=tenant_id,
                connected_mailbox_id=connected_mailbox_id,
                status=InvoiceStatus.PENDING,
                file_hash=file_hash,
                currency="AUD",
                email_sender=email.sender or None,
                email_subject=email.subject or None,
                email_attachment_name=att.filename,
                email_message_id=email.message_id,
                storage_vendor_slug=vendor_slug,
            )
            session.add(inv)
            await session.flush()
            await assign_document_ref(session, inv)

            await apply_ingest_capture(session, inv, email, att)

            stored = store_invoice_pdf(
                att.data,
                tenant_id,
                tenant_slug,
                vendor_slug,
                inv.id,
                file_hash,
                att.filename,
                tenant_name=tenant_name,
                route_target=inv.route_target,
            )
            inv.raw_file_path = stored

            await log_event(
                session,
                "email_ingested",
                invoice_id=inv.id,
                detail={
                    "subject": email.subject,
                    "sender": email.sender,
                    "message_id": email.message_id,
                    "vendor_slug": vendor_slug,
                    "storage": stored,
                },
            )
            result.ingested_count += 1

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

    await repair_invoice_stored_path(session, invoice)

    if not stored_file_available(invoice.raw_file_path, tenant_id=invoice.tenant_id):
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

    invoice.status = InvoiceStatus.PARSING
    await session.flush()
    try:
        with open_pdf_for_reading(invoice.raw_file_path, tenant_id=invoice.tenant_id) as path:
            parse_result = parse_invoice(path)
    except (OSError, FileNotFoundError) as exc:
        invoice.status = InvoiceStatus.EXCEPTION
        await log_event(
            session,
            "parsing_failed",
            invoice_id=invoice.id,
            detail=audit_document_detail(invoice, reason="file_read_failed", error=str(exc)),
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    parsed = parse_result.data
    await log_event(
        session,
        "parse_completed",
        invoice_id=invoice.id,
        detail={
            "source": parse_result.source,
            "confidence": parse_result.confidence,
            "text_length": parse_result.text_length,
        },
    )

    config = await load_config_for_tenant(session, invoice.tenant_id)
    resolved_vendor = resolve_canonical_vendor_name(
        invoice.tenant_id,
        vendor_names=[parsed.vendor],
        abns=[parsed.abn],
        config=config,
    )
    if not resolved_vendor and parsed.vendor and is_plausible_vendor_name(parsed.vendor):
        resolved_vendor = parsed.vendor

    _apply_parsed_scalar(invoice, "vendor", resolved_vendor)
    _apply_parsed_scalar(invoice, "abn", parsed.abn)
    _apply_parsed_scalar(invoice, "billing_address", parsed.billing_address)
    _apply_parsed_scalar(invoice, "bank_bsb", parsed.bank_bsb)
    _apply_parsed_scalar(invoice, "bank_account", parsed.bank_account)
    _apply_parsed_scalar(invoice, "invoice_no", parsed.invoice_no)
    _apply_parsed_scalar(invoice, "po_reference", parsed.po_reference)
    _apply_parsed_scalar(invoice, "cost_centre", parsed.cost_centre)
    _apply_parsed_scalar(invoice, "invoice_date", parsed.invoice_date)
    _apply_parsed_scalar(invoice, "due_date", parsed.due_date)
    if _scalar_field_empty(invoice.subtotal):
        invoice.subtotal = plausible_money(parsed.subtotal)
    if _scalar_field_empty(invoice.gst):
        invoice.gst = plausible_money(parsed.gst)
    if _scalar_field_empty(invoice.total):
        invoice.total = plausible_money(parsed.total)
    _apply_parsed_scalar(invoice, "currency", parsed.currency)
    from app.services.document_text import cap_document_text
    from app.services.po_reference import effective_po_reference, extract_po_reference_from_text

    if _scalar_field_empty(invoice.document_text):
        invoice.document_text = cap_document_text(parsed.document_text)
    if not effective_po_reference(invoice.po_reference):
        extracted = extract_po_reference_from_text(invoice.document_text)
        if extracted:
            invoice.po_reference = extracted
            parsed.po_reference = extracted

    existing_line_count = (
        await session.execute(
            select(LineItem.id).where(*line_items_for_invoice(invoice.tenant_id, invoice.id))
        )
    ).scalars().all()
    if not existing_line_count:
        await _replace_line_items(session, invoice, parsed.line_items)

    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice.id)
        .options(selectinload(Invoice.line_items))
    )
    loaded = (await session.execute(stmt)).scalar_one()

    segment_heading_kind = await load_segment_heading_kind_from_audit(session, invoice.id)
    classification = classify_document_type(
        invoice=loaded,
        parsed=parsed,
        document_types=config.document_types,
        parse_confidence=parse_result.confidence,
        unclassified=config.document_classification,
        segment_heading_kind=segment_heading_kind,
    )
    apply_document_type_classification(loaded, classification)
    invoice.document_type_code = loaded.document_type_code
    invoice.document_type_confidence = loaded.document_type_confidence
    await log_event(
        session,
        "document_classified",
        invoice_id=invoice.id,
        detail=classification_audit_detail(
            classification,
            document_types=config.document_types,
        ),
    )

    await apply_invoice_evaluation(session, loaded, config=config)
    from app.services.purchase_document_service import apply_purchase_document_type_after_eval

    await apply_purchase_document_type_after_eval(session, loaded)

    await sync_invoice_blob_path(session, loaded, parsed_vendor=resolved_vendor)
    invoice.raw_file_path = loaded.raw_file_path
    invoice.storage_vendor_slug = loaded.storage_vendor_slug
    invoice.route_target = loaded.route_target

    classifier_matches = list_heading_aware_document_type_matches(
        list(config.document_types),
        invoice=loaded,
        parsed=parsed,
        heading_kind=segment_heading_kind,
    )
    no_classifier_match = not classifier_matches
    dt_definition = resolve_definition_for_invoice(loaded, list(config.document_types))

    if requires_classification_review(loaded, classification) and not bypass_review_gates:
        loaded.evaluation_status = EVAL_NEEDS_REVIEW
        invoice.evaluation_status = EVAL_NEEDS_REVIEW
        invoice.status = InvoiceStatus.EXCEPTION
        await log_event(
            session,
            "routing_review_required",
            invoice_id=invoice.id,
            detail={
                "gate": "classification",
                "document_type_code": loaded.document_type_code,
                "document_type_confidence": loaded.document_type_confidence,
                "route_target": invoice.route_target,
                "reason": classification.reason,
                "no_classifier_match": no_classifier_match,
                "needs_review": classification.needs_review,
            },
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

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
                "reason": classification.reason,
                "no_classifier_match": no_classifier_match,
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
        if no_classifier_match and not (loaded.document_type_code or "").strip()
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
