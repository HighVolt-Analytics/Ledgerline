"""Team expense side effects after invoice processing."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM
from app.services.master_data.master_data_service import (
    get_employee_master_by_id,
    list_employee_masters,
    sync_masters_to_config_file,
)
from app.services.purchase.team_expense_validator import (
    find_employee_by_sender,
    resolve_employee_for_sender,
)


async def stamp_team_expense_employee_identity(
    session: AsyncSession,
    invoice: Invoice,
) -> str | None:
    """Fill empty TE counterparty with the matched employee registry name.

    DT-03 labels ``vendor`` as Employee in the UI. Vision often leaves counterparty
    empty on internal claim forms even when the sender matches the employee master
    (VR-TE01 already passed) — without this stamp the drawer shows "Unknown employee".
    """
    if (invoice.route_target or "").strip() != ROUTE_TEAM:
        return None
    if (invoice.vendor or "").strip():
        return (invoice.vendor or "").strip()

    employee = await resolve_employee_for_sender(
        session,
        invoice.tenant_id,
        invoice.email_sender,
    )
    name = (employee.name if employee else None) or ""
    name = name.strip()
    if not name:
        return None

    invoice.vendor = name
    from app.services.extraction.extraction_field_values import merge_invoice_extracted_fields

    merge_invoice_extracted_fields(invoice, {"vendor": name})
    return name


async def record_team_expense_processed(
    session: AsyncSession,
    invoice: Invoice,
) -> None:
    """Increment employee MTD/YTD spend when a team expense invoice is processed."""
    if invoice.status != InvoiceStatus.PROCESSED:
        return
    if invoice.route_target != ROUTE_TEAM:
        return
    if not invoice.email_sender or invoice.total is None:
        return

    employees = await list_employee_masters(session, invoice.tenant_id)
    employee = find_employee_by_sender(employees, invoice.email_sender)
    if employee is None:
        return

    row = await get_employee_master_by_id(session, invoice.tenant_id, employee.id)
    if row is None:
        return

    amount = float(invoice.total)
    row.mtd_spent = (row.mtd_spent or 0) + amount
    row.qtd_spent = (row.qtd_spent or 0) + amount
    row.ytd_spent = (row.ytd_spent or 0) + amount
    row.claim_count = (row.claim_count or 0) + 1
    row.last_claim = (invoice.invoice_date or date.today()).isoformat()
    await session.flush()
    await sync_masters_to_config_file(session, invoice.tenant_id)
