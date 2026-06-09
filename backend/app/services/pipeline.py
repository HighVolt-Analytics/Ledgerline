"""Run the invoice processing pipeline for one PDF."""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.models.organisation import Organisation
from app.models.journal import JournalEntry
from app.models.line_item import LineItem
from app.models.vendor import VendorRegistry
from app.services.account_mapper import AccountMapping, MappingDetail
from app.services.ingest_capture_service import apply_ingest_capture, evaluate_ingest_capture
from app.services.invoice_evaluation_service import apply_invoice_evaluation, load_config_for_org
from app.services.rule_book_mapper import is_fallback_mapping, map_invoice_with_details
from app.services.team_expense_approval import team_expense_auto_approve_eligible
from app.services.team_expense_service import record_team_expense_processed
from app.services.team_expense_validator import invoice_to_eval_document_from_data
from app.services.vendor_hold_service import apply_vendor_hold_if_needed
from app.services.invoice_data import ParsedLineItem
from app.services.attachment_filter import filter_invoice_attachments
from app.services.audit_service import log_event
from app.services.email_ingestion import RawEmail, mark_message_read
from app.services.file_storage import open_pdf_for_reading, relocate_invoice_pdf, store_invoice_pdf
from app.services.vault_paths import filename_from_stored
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


async def _replace_line_items(
    session: AsyncSession,
    invoice: Invoice,
    lines: list[ParsedLineItem],
) -> None:
    await session.execute(delete(LineItem).where(LineItem.invoice_id == invoice.id))
    await session.flush()
    for line in lines:
        session.add(
            LineItem(
                invoice_id=invoice.id,
                description=line.description,
                qty=line.qty,
                unit_price=line.unit_price,
                amount=line.amount,
                tax_amount=line.tax_amount,
            )
        )


def _resolve_header_mapping(invoice: Invoice) -> tuple[AccountMapping, MappingDetail]:
    """Map invoice header using unified classification config."""
    if not invoice.line_items:
        detail = map_invoice_with_details(invoice)
        return (
            AccountMapping(
                account_code=detail.account_code,
                account_name=detail.account_name,
                expense_category=detail.expense_category,
            ),
            detail,
        )
    best_detail = map_invoice_with_details(invoice)
    best = AccountMapping(
        account_code=best_detail.account_code,
        account_name=best_detail.account_name,
        expense_category=best_detail.expense_category,
    )
    for line in invoice.line_items:
        detail = map_invoice_with_details(invoice, line_description=line.description)
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
    org_id: int,
) -> Invoice | None:
    stmt = select(Invoice).where(
        Invoice.file_hash == file_hash,
        Invoice.org_id == org_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _org_slug(session: AsyncSession, org_id: int) -> str:
    org = await session.get(Organisation, org_id)
    if org:
        return org.slug
    return get_settings().default_org_slug


async def _post_parse_relocate(
    session: AsyncSession,
    invoice: Invoice,
    parsed_vendor: str | None,
) -> None:
    if not invoice.raw_file_path or not invoice.file_hash:
        return

    settings = get_settings()
    if settings.blob_auto_relocate_unknown:
        new_slug = await resolve_storage_slug_for_parsed_vendor(
            session, parsed_vendor, org_id=invoice.org_id
        )
        old_slug = invoice.storage_vendor_slug or UNKNOWN_SLUG
        if new_slug != old_slug:
            if new_slug != UNKNOWN_SLUG or not is_valid_storage_slug(old_slug):
                invoice.storage_vendor_slug = new_slug

    org = await session.get(Organisation, invoice.org_id)
    org_slug = org.slug if org else settings.default_org_slug
    org_name = org.name if org else None
    filename = _filename_from_stored(invoice.raw_file_path, invoice.id, invoice.file_hash)
    new_path = relocate_invoice_pdf(
        invoice.raw_file_path,
        org_slug,
        invoice.storage_vendor_slug or UNKNOWN_SLUG,
        invoice.id,
        invoice.file_hash,
        filename,
        org_name=org_name,
        vendor_name=invoice.vendor or parsed_vendor,
        invoice_no=invoice.invoice_no,
        invoice_date=invoice.invoice_date,
    )
    if new_path != invoice.raw_file_path:
        invoice.raw_file_path = new_path
        await log_event(
            session,
            "blob_relocated",
            invoice_id=invoice.id,
            detail={
                "vendor_slug": invoice.storage_vendor_slug,
                "path": new_path,
            },
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
            select(VendorRegistry).where(VendorRegistry.org_id == invoice.org_id)
        )
    ).scalars().all()
    for row in rows:
        if row.sender_pattern.lower() == invoice.email_sender.lower():
            return
        if row.vendor_slug == invoice.storage_vendor_slug:
            return

    session.add(
        VendorRegistry(
            org_id=invoice.org_id,
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


def _finish_email_message(message_id: str, mailbox_email: str) -> None:
    """Mark read when folder moves are disabled (legacy behaviour)."""
    if not folder_moves_enabled():
        mark_message_read(message_id, mailbox_email)


async def ingest_email_attachments(
    session: AsyncSession,
    emails: list[RawEmail],
    *,
    org_id: int,
    org_slug: str,
    connected_mailbox_id: int | None = None,
) -> EmailIngestResult:
    """Save invoice attachments (PDF/image/DOCX) from emails."""
    result = EmailIngestResult()
    org = await session.get(Organisation, org_id)
    org_name = org.name if org else None

    capture_config = load_config_for_org(org_id)

    for email in emails:
        result.message_ids.append(email.message_id)

        if not email.attachments:
            await log_event(
                session,
                "email_skipped",
                detail={"reason": "no_attachments", "message_id": email.message_id},
            )
            result.preskip_exceptions[email.message_id] = "no_attachments"
            _finish_email_message(email.message_id, email.mailbox_email)
            continue

        attachments = filter_invoice_attachments(email)
        if not attachments:
            await log_event(
                session,
                "email_skipped",
                detail={"reason": "no_invoice_attachments", "message_id": email.message_id},
            )
            result.preskip_exceptions[email.message_id] = "no_invoice_attachments"
            _finish_email_message(email.message_id, email.mailbox_email)
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
            existing = await find_by_hash(session, file_hash, org_id=org_id)
            if existing:
                existing.email_message_id = email.message_id
                if existing.status != InvoiceStatus.PROCESSED:
                    continue
                existing.status = InvoiceStatus.DUPLICATE_SKIPPED
                await log_event(
                    session,
                    "duplicate_skipped",
                    invoice_id=existing.id,
                    detail={"filename": att.filename, "message_id": email.message_id},
                )
                continue

            vendor_slug = await resolve_vendor_slug(
                session, email.sender, org_id=org_id
            )
            inv = Invoice(
                org_id=org_id,
                connected_mailbox_id=connected_mailbox_id,
                status=InvoiceStatus.PENDING,
                file_hash=file_hash,
                currency="AUD",
                email_sender=email.sender or None,
                email_message_id=email.message_id,
                storage_vendor_slug=vendor_slug,
            )
            session.add(inv)
            await session.flush()

            await apply_ingest_capture(session, inv, email, att)

            stored = store_invoice_pdf(
                att.data,
                org_slug,
                vendor_slug,
                inv.id,
                file_hash,
                att.filename,
                org_name=org_name,
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

        _finish_email_message(email.message_id, email.mailbox_email)

    return result


async def process_invoice(session: AsyncSession, invoice: Invoice) -> None:
    """Parse → validate → map → journal → reconcile for one invoice."""
    if invoice.status in (
        InvoiceStatus.PROCESSED,
        InvoiceStatus.DUPLICATE_SKIPPED,
        InvoiceStatus.REJECTED,
    ):
        return

    if not invoice.raw_file_path:
        invoice.status = InvoiceStatus.EXCEPTION
        await log_event(session, "parsing_failed", invoice_id=invoice.id)
        return

    invoice.status = InvoiceStatus.PARSING
    await session.flush()
    try:
        with open_pdf_for_reading(invoice.raw_file_path) as path:
            parse_result = parse_invoice(path)
    except OSError:
        invoice.status = InvoiceStatus.EXCEPTION
        await log_event(session, "parsing_failed", invoice_id=invoice.id)
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

    invoice.vendor = parsed.vendor
    invoice.abn = parsed.abn
    invoice.invoice_no = parsed.invoice_no
    invoice.po_reference = parsed.po_reference
    invoice.cost_centre = parsed.cost_centre
    invoice.invoice_date = parsed.invoice_date
    invoice.due_date = parsed.due_date
    invoice.subtotal = parsed.subtotal
    invoice.gst = parsed.gst
    invoice.total = parsed.total
    invoice.currency = parsed.currency

    await _replace_line_items(session, invoice, parsed.line_items)

    await _post_parse_relocate(session, invoice, parsed.vendor)

    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice.id)
        .options(selectinload(Invoice.line_items))
    )
    loaded = (await session.execute(stmt)).scalar_one()
    await apply_invoice_evaluation(session, loaded)

    if await apply_vendor_hold_if_needed(session, loaded):
        invoice.status = InvoiceStatus.EXCEPTION
        return

    invoice.status = InvoiceStatus.VALIDATING
    await session.flush()
    results = await run_all_validations(
        parsed,
        session,
        invoice.id,
        org_id=invoice.org_id,
        sender=invoice.email_sender,
        route_target=invoice.route_target,
    )
    invoice.validation_results = results_to_json(results)
    invoice.abn = parsed.abn
    if not all_passed(results):
        from app.services.rule_engine import match_team_expense_rule

        config = load_config_for_org(invoice.org_id)
        amount = float(parsed.total) if parsed.total is not None else None
        doc = invoice_to_eval_document_from_data(parsed, invoice.email_sender)
        team_rule = match_team_expense_rule(
            doc,
            config.team_expense_rules,
            amount=amount,
        )
        if team_expense_auto_approve_eligible(
            results,
            route_target=invoice.route_target,
            amount=amount,
            team_rule=team_rule,
        ):
            await log_event(
                session,
                "team_expense_auto_approved",
                invoice_id=invoice.id,
                detail={"amount": amount, "rule_id": team_rule.id if team_rule else None},
            )
        else:
            stmt = (
                select(Invoice)
                .where(Invoice.id == invoice.id)
                .options(selectinload(Invoice.line_items))
            )
            loaded = (await session.execute(stmt)).scalar_one()
            await apply_invoice_evaluation(session, loaded)
            if await apply_vendor_hold_if_needed(session, loaded):
                invoice.status = InvoiceStatus.EXCEPTION
                return
            invoice.status = InvoiceStatus.EXCEPTION
            await log_event(session, "validation_failed", invoice_id=invoice.id)
            send_notification(invoice, InvoiceStatus.EXCEPTION)
            return

    await log_event(session, "validation_passed", invoice_id=invoice.id)

    post_validate = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    if await apply_vendor_hold_if_needed(session, post_validate):
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
    mapping, mapping_detail = _resolve_header_mapping(loaded)
    invoice.account_code = mapping.account_code
    invoice.account_name = mapping.account_name
    await apply_invoice_evaluation(session, loaded)
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

    invoice.status = InvoiceStatus.JOURNALING
    await session.flush()
    existing_entries = (
        await session.execute(
            select(JournalEntry).where(JournalEntry.invoice_id == invoice.id)
        )
    ).scalars().all()
    for entry in existing_entries:
        await session.delete(entry)
    await session.flush()
    for line in generate_entries(invoice, mapping):
        session.add(
            JournalEntry(
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
        session, recon_date, org_id=invoice.org_id, current_invoice=invoice
    )
    await save_reconciliation(session, recon)
    if recon.halted:
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
    await _auto_learn_sender(session, invoice)
    await log_event(session, "invoice_processed", invoice_id=invoice.id)
    send_notification(invoice, InvoiceStatus.PROCESSED)
