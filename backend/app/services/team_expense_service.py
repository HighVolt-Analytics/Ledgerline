"""Team expense side effects after invoice processing."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice_evaluation_service import ROUTE_TEAM
from app.services.master_data_service import (
    get_employee_master_by_id,
    list_employee_masters,
    sync_masters_to_config_file,
)
from app.services.team_expense_validator import _find_employee_by_sender


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

    employees = await list_employee_masters(session, invoice.org_id)
    employee = _find_employee_by_sender(employees, invoice.email_sender)
    if employee is None:
        return

    row = await get_employee_master_by_id(session, invoice.org_id, employee.id)
    if row is None:
        return

    amount = float(invoice.total)
    row.mtd_spent = (row.mtd_spent or 0) + amount
    row.qtd_spent = (row.qtd_spent or 0) + amount
    row.ytd_spent = (row.ytd_spent or 0) + amount
    row.claim_count = (row.claim_count or 0) + 1
    row.last_claim = (invoice.invoice_date or date.today()).isoformat()
    await session.flush()
    await sync_masters_to_config_file(session, invoice.org_id)
