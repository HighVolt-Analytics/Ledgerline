"""Approve / reject workflows for the approval queue."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.organisation import Organisation
from app.services.audit_service import log_event
from app.services.file_storage import (
    delete_stored_file,
    relocate_invoice_to_rejected,
    relocate_rejected_to_vault,
    repair_invoice_stored_path,
    stored_file_available,
)
from app.services.invoice_evaluation_service import load_config_for_org
from app.services.invoice_reset import clear_invoice_posting_artifacts, reset_invoice_for_reprocess
from app.services.team_expense_approval import assert_team_expense_approvable
from app.services.vault_invoice_paths import vault_document_type_titles_for_invoice
from app.services.vault_paths import filename_from_stored

_QUEUE_STATUSES = frozenset(
    {
        InvoiceStatus.EXCEPTION,
        InvoiceStatus.DUPLICATE_SKIPPED,
        InvoiceStatus.REJECTED,
    }
)

_REJECTABLE = frozenset({InvoiceStatus.EXCEPTION, InvoiceStatus.PROCESSED})

_APPROVABLE = frozenset(
    {
        InvoiceStatus.EXCEPTION,
        InvoiceStatus.DUPLICATE_SKIPPED,
        InvoiceStatus.REJECTED,
    }
)

_DELETABLE = frozenset(
    {InvoiceStatus.REJECTED, InvoiceStatus.DUPLICATE_SKIPPED}
)

_REQUESTABLE = frozenset(
    {
        InvoiceStatus.PROCESSED,
        InvoiceStatus.PENDING,
        InvoiceStatus.PARSING,
        InvoiceStatus.VALIDATING,
        InvoiceStatus.MAPPING,
        InvoiceStatus.JOURNALING,
        InvoiceStatus.RECONCILING,
    }
)


def is_queue_status(status: InvoiceStatus) -> bool:
    return status in _QUEUE_STATUSES


async def reject_invoice(
    session: AsyncSession,
    inv: Invoice,
    *,
    actor_name: str | None = None,
    actor_email: str | None = None,
) -> None:
    """Mark invoice rejected and move stored file to rejected/{org}/{vendor}/{year}/{month}/."""
    if inv.status not in _REJECTABLE:
        raise ValueError(f"Invoice status '{inv.status.value}' cannot be rejected")

    org = await session.get(Organisation, inv.org_id)
    org_slug = org.slug if org else "default"
    org_name = org.name if org else None
    config = load_config_for_org(inv.org_id)
    short_title, title = vault_document_type_titles_for_invoice(inv, list(config.document_types))

    previous_status = inv.status.value
    old_path = inv.raw_file_path

    if inv.raw_file_path and stored_file_available(inv.raw_file_path):
        filename = filename_from_stored(inv.raw_file_path)
        new_path = relocate_invoice_to_rejected(
            inv.raw_file_path,
            org_slug,
            inv.id,
            filename,
            org_name=org_name,
            vendor_name=inv.vendor,
            storage_vendor_slug=inv.storage_vendor_slug,
            invoice_no=inv.invoice_no,
            invoice_date=inv.invoice_date,
            route_target=inv.route_target,
            document_type_code=inv.document_type_code,
            document_type_short_title=short_title,
            document_type_title=title,
        )
        if new_path != inv.raw_file_path:
            inv.raw_file_path = new_path

    if inv.status == InvoiceStatus.PROCESSED:
        await clear_invoice_posting_artifacts(session, inv)

    inv.status = InvoiceStatus.REJECTED
    await session.flush()
    await log_event(
        session,
        "invoice_rejected",
        invoice_id=inv.id,
        detail={
            "previous_status": previous_status,
            "old_path": old_path,
            "new_path": inv.raw_file_path,
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )


async def approve_invoice_for_reprocess(
    session: AsyncSession,
    inv: Invoice,
    *,
    actor_name: str | None = None,
    actor_email: str | None = None,
) -> None:
    """Reset invoice for pipeline; restore file from rejected/ to invoice/ when needed."""
    if inv.status not in _APPROVABLE:
        raise ValueError(f"Invoice status '{inv.status.value}' is not in the approval queue")

    loaded = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == inv.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    await assert_team_expense_approvable(session, loaded)
    await repair_invoice_stored_path(session, inv)
    if not stored_file_available(inv.raw_file_path):
        raise ValueError("Invoice has no stored file to process")

    org = await session.get(Organisation, inv.org_id)
    org_slug = org.slug if org else "default"
    org_name = org.name if org else None
    config = load_config_for_org(inv.org_id)
    short_title, title = vault_document_type_titles_for_invoice(inv, list(config.document_types))
    previous_status = inv.status.value

    if inv.status == InvoiceStatus.REJECTED and inv.raw_file_path:
        filename = filename_from_stored(inv.raw_file_path)
        inv.raw_file_path = relocate_rejected_to_vault(
            inv.raw_file_path,
            org_slug,
            inv.storage_vendor_slug or "unknown",
            inv.id,
            inv.file_hash or "",
            filename,
            org_name=org_name,
            vendor_name=inv.vendor,
            invoice_no=inv.invoice_no,
            invoice_date=inv.invoice_date,
            route_target=inv.route_target,
            document_type_code=inv.document_type_code,
            document_type_short_title=short_title,
            document_type_title=title,
        )

    await reset_invoice_for_reprocess(session, inv)
    await log_event(
        session,
        "invoice_approved",
        invoice_id=inv.id,
        detail={"previous_status": previous_status},
        actor_name=actor_name,
        actor_email=actor_email,
    )


async def request_approval(
    session: AsyncSession,
    inv: Invoice,
    *,
    actor_name: str | None = None,
    actor_email: str | None = None,
) -> None:
    """Route an invoice to the human approval queue."""
    if inv.status in _QUEUE_STATUSES:
        raise ValueError("Invoice is already in the approval queue")
    if inv.status not in _REQUESTABLE:
        raise ValueError(f"Invoice status '{inv.status.value}' cannot request approval")

    previous_status = inv.status.value
    inv.status = InvoiceStatus.EXCEPTION
    await session.flush()
    await log_event(
        session,
        "approval_requested",
        invoice_id=inv.id,
        detail={"previous_status": previous_status},
        actor_name=actor_name,
        actor_email=actor_email,
    )


async def permanently_delete_invoice(session: AsyncSession, inv: Invoice) -> None:
    """Permanently remove a rejected/duplicate invoice and its stored file."""
    if inv.status not in _DELETABLE:
        raise ValueError(
            f"Invoice status '{inv.status.value}' cannot be permanently deleted"
        )

    stored_path = inv.raw_file_path
    await log_event(
        session,
        "invoice_permanently_deleted",
        invoice_id=inv.id,
        detail={
            "status": inv.status.value,
            "vendor": inv.vendor,
            "invoice_no": inv.invoice_no,
            "stored_path": stored_path,
        },
    )
    delete_stored_file(stored_path)
    await session.delete(inv)
    await session.flush()
