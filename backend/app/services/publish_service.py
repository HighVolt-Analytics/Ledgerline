"""Ledger publish — workbook export, billing credits, audit trail."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.tenant_child_tables import journal_entries_for_invoice
from app.services.audit_service import log_event
from app.services.billing_io import load_billing_for_tenant, save_billing_for_tenant
from app.services.document_ref_service import display_document_ref
from app.services.workbook_writer import write_workbook_for_invoice

PUBLISH_CREDIT_COST = 5
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
    return latest_publish > latest_processed


class InsufficientCreditsError(Exception):
    def __init__(self, balance: int, required: int) -> None:
        self.balance = balance
        self.required = required
        super().__init__(f"Insufficient credits: need {required}, balance {balance}")


async def published_invoice_ids(
    session: AsyncSession,
    invoice_ids: list[int],
) -> set[int]:
    if not invoice_ids:
        return set()
    rows = (
        await session.execute(
            select(AuditLog.invoice_id, AuditLog.event, func.max(AuditLog.id))
            .where(
                AuditLog.invoice_id.in_(invoice_ids),
                AuditLog.event.in_(
                    [
                        "invoice_published_to_ledger",
                        *PROCESSED_LEDGER_EVENTS,
                    ]
                ),
            )
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
        if publish_id > processed_id:
            published.add(invoice_id)
    return published


async def is_published_to_ledger(session: AsyncSession, invoice_id: int) -> bool:
    return invoice_id in await published_invoice_ids(session, [invoice_id])


def _deduct_publish_credits(tenant_id: int, *, skip_if_insufficient: bool) -> bool:
    """Return True when credits were deducted; False when skipped (auto path only)."""
    state = load_billing_for_tenant(tenant_id)
    if state.balance < PUBLISH_CREDIT_COST:
        if skip_if_insufficient:
            return False
        raise InsufficientCreditsError(state.balance, PUBLISH_CREDIT_COST)
    state.balance -= PUBLISH_CREDIT_COST
    save_billing_for_tenant(tenant_id, state)
    return True


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
    if invoice.status != InvoiceStatus.PROCESSED:
        raise ValueError(
            f"Only processed invoices can be published (current: {invoice.status.value})"
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
        raise ValueError("No journal entries to publish")

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
        raise ValueError("Invoice date is required before publishing to ledger")

    credits_charged = _deduct_publish_credits(
        invoice.tenant_id,
        skip_if_insufficient=auto and skip_if_insufficient_credits,
    )
    if not credits_charged and auto:
        await log_event(
            session,
            "publish_skipped",
            invoice_id=invoice.id,
            detail={
                "reason": "insufficient_credits",
                "required": PUBLISH_CREDIT_COST,
                "document_ref": display_document_ref(invoice),
            },
            actor_name=actor_name or "System",
            actor_email=actor_email,
        )
        return False

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
            "credits_charged": PUBLISH_CREDIT_COST if credits_charged else 0,
            "auto": auto,
        },
        actor_name=actor_name or ("System" if auto else None),
        actor_email=actor_email,
    )
    return True
