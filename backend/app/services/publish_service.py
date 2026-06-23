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
            select(AuditLog.invoice_id).where(
                AuditLog.invoice_id.in_(invoice_ids),
                AuditLog.event == "invoice_published_to_ledger",
            )
        )
    ).scalars().all()
    return {row for row in rows if row is not None}


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

    await write_workbook_for_invoice(session, invoice)

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
