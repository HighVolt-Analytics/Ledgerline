"""Ledger publish — workbook export and audit trail."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.tenant_child_tables import journal_entries_for_invoice
from app.services.audit.audit_service import log_event
from app.services.dossier.document_ref_service import display_document_ref
from app.services.invoice.processing_cycle_service import (
    CYCLE_RESET_EVENTS,
    latest_cycle_reset_log_id_from_logs,
)
from app.services.reports.workbook_writer import write_workbook_for_invoice

PUBLISH_TARGET = "workbook"
PROCESSED_LEDGER_EVENTS = frozenset(
    {"invoice_processed", "purchase_document_processed"},
)


def is_published_from_audit_logs(logs: list[AuditLog]) -> bool:
    """True when the latest ledger publish is newer than the latest process cycle."""
    latest_publish = max(
        (log.id for log in logs if log.event == "invoice_published_to_ledger"),
        default=0,
    )
    if latest_publish == 0:
        return False
    latest_processed = max(
        (log.id for log in logs if log.event in PROCESSED_LEDGER_EVENTS),
        default=0,
    )
    reset_id = latest_cycle_reset_log_id_from_logs(logs)
    return latest_publish > max(latest_processed, reset_id)


class InsufficientCreditsError(Exception):
    def __init__(self, balance: int, required: int) -> None:
        self.balance = balance
        self.required = required
        super().__init__(f"Insufficient credits: need {required}, balance {balance}")


async def published_invoice_ids(
    session: AsyncSession,
    invoice_ids: list[int],
    *,
    tenant_id=None,
) -> set[int]:
    if not invoice_ids:
        return set()
    from app.tenant_scoped import coerce_tenant_uuid

    filters = [
        AuditLog.invoice_id.in_(invoice_ids),
        AuditLog.event.in_(
            [
                "invoice_published_to_ledger",
                *PROCESSED_LEDGER_EVENTS,
                *CYCLE_RESET_EVENTS,
            ]
        ),
    ]
    tid = coerce_tenant_uuid(tenant_id)
    if tid is not None:
        filters.append(AuditLog.tenant_id == tid)
    rows = (
        await session.execute(
            select(AuditLog.invoice_id, AuditLog.event, func.max(AuditLog.id))
            .where(*filters)
            .group_by(AuditLog.invoice_id, AuditLog.event)
        )
    ).all()
    by_invoice: dict[int, dict[str, int]] = {}
    for invoice_id, event, max_id in rows:
        if invoice_id is None:
            continue
        by_invoice.setdefault(invoice_id, {})[event] = max_id
    published: set[int] = set()
    for invoice_id in invoice_ids:
        events = by_invoice.get(invoice_id, {})
        publish_id = events.get("invoice_published_to_ledger", 0)
        if publish_id == 0:
            continue
        processed_id = max(
            events.get("invoice_processed", 0),
            events.get("purchase_document_processed", 0),
        )
        reset_id = max(
            events.get("invoice_rejected", 0),
            events.get("invoice_requeued", 0),
            events.get("duplicate_reingest_rejected", 0),
        )
        if publish_id > max(processed_id, reset_id):
            published.add(invoice_id)
    return published


async def is_published_to_ledger(session: AsyncSession, invoice_id: int) -> bool:
    return invoice_id in await published_invoice_ids(session, [invoice_id])


async def publish_invoice_to_ledger(
    session: AsyncSession,
    invoice: Invoice,
    *,
    actor_name: str | None = None,
    actor_email: str | None = None,
    auto: bool = False,
    skip_if_insufficient_credits: bool = False,
) -> bool:
    """
    Export journal rows to the org workbook and record ledger publish.

    Returns True when a new publish was recorded; False when already published.
    """
    _ = skip_if_insufficient_credits  # credits charged on upload
    if invoice.status != InvoiceStatus.PROCESSED:
        raise ValueError(
            f"Only processed invoices can be posted (current: {invoice.status.value})"
        )
    if await is_published_to_ledger(session, invoice.id):
        return False

    journal_count = (
        await session.execute(
            select(func.count())
            .select_from(JournalEntry)
            .where(*journal_entries_for_invoice(invoice.tenant_id, invoice.id))
        )
    ).scalar() or 0
    if journal_count == 0:
        raise ValueError("No journal entries to post")

    if not invoice.invoice_date:
        if auto:
            await log_event(
                session,
                "publish_skipped",
                invoice_id=invoice.id,
                detail={
                    "reason": "missing_invoice_date",
                    "document_ref": display_document_ref(invoice),
                },
                actor_name=actor_name or "System",
                actor_email=actor_email,
            )
            return False
        raise ValueError("Invoice date is required before posting to ledger")

    workbook_path = await write_workbook_for_invoice(session, invoice)
    if workbook_path is None:
        if auto:
            await log_event(
                session,
                "publish_skipped",
                invoice_id=invoice.id,
                detail={
                    "reason": "workbook_export_failed",
                    "document_ref": display_document_ref(invoice),
                },
                actor_name=actor_name or "System",
                actor_email=actor_email,
            )
            return False
        raise ValueError("Workbook export failed — check invoice date and journal lines")

    doc_ref = display_document_ref(invoice)
    await log_event(
        session,
        "invoice_published_to_ledger",
        invoice_id=invoice.id,
        detail={
            "target": PUBLISH_TARGET,
            "document_ref": doc_ref,
            "vendor": invoice.vendor,
            "invoice_no": invoice.invoice_no,
            "auto": auto,
        },
        actor_name=actor_name or ("System" if auto else None),
        actor_email=actor_email,
    )
    return True
