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
from app.services.purchase.team_expense_spend_service import (
    counts_toward_spend,
    normalize_employee_email,
    rebuild_employee_spend_cache,
)
from app.services.purchase.team_expense_validator import (
    find_employee_by_sender,
    resolve_employee_for_sender,
    resolve_team_expense_employee,
)


async def stamp_team_expense_employee_identity(
    session: AsyncSession,
    invoice: Invoice,
) -> str | None:
    """Stamp permanent employee_email (+ employee_name) from Employee Master.

    Employee name/email come from the Employee Master row matched to the mail
    sender (or stamped ``employee_email``) — never from receipt OCR/LLM.
    After ``employee_email`` is set, later TE logic must use that field — never
    re-guess from ``email_sender``.
    """
    employees = await list_employee_masters(session, invoice.tenant_id)
    employee = resolve_team_expense_employee(
        employees,
        employee_email=getattr(invoice, "employee_email", None),
        email_sender=invoice.email_sender,
    )
    is_team = (invoice.route_target or "").strip() == ROUTE_TEAM
    if employee is None:
        # Do not leave OCR "customer name" sitting in employee_name.
        fields = getattr(invoice, "extracted_fields", None) or {}
        if isinstance(fields, dict) and fields.get("employee_name"):
            cleaned = {k: v for k, v in fields.items() if k != "employee_name"}
            invoice.extracted_fields = cleaned or None
        if not is_team:
            return None
        return (invoice.vendor or "").strip() or None

    canonical = normalize_employee_email(employee.email)
    if canonical and not (invoice.employee_email or "").strip():
        invoice.employee_email = canonical
    elif canonical and normalize_employee_email(invoice.employee_email) != canonical:
        # Keep first stamp; do not overwrite.
        pass
    elif canonical and not normalize_employee_email(invoice.employee_email):
        invoice.employee_email = canonical

    if not (invoice.employee_email or "").strip() and canonical:
        invoice.employee_email = canonical

    name = (employee.name or "").strip()
    if name:
        from app.services.extraction.extraction_field_values import (
            merge_invoice_extracted_fields,
        )

        # Always prefer Employee Master over OCR/LLM (receipt text is not the claimant).
        merge_invoice_extracted_fields(invoice, {"employee_name": name})
        # Back-compat: older TE UIs used vendor as the employee display name.
        # Only fill when empty so merchant OCR on the receipt is preserved.
        if is_team and not (invoice.vendor or "").strip():
            invoice.vendor = name
            merge_invoice_extracted_fields(invoice, {"vendor": name})
    fields = getattr(invoice, "extracted_fields", None) or {}
    stamped = (fields.get("employee_name") or "").strip() if isinstance(fields, dict) else ""
    return stamped or name or ((invoice.vendor or "").strip() if is_team else None) or None


async def record_team_expense_processed(
    session: AsyncSession,
    invoice: Invoice,
) -> None:
    """Rebuild employee spend cache when a real expense claim is processed.

    Advance requisitions are cash float, not period spend.
    """
    if invoice.status != InvoiceStatus.PROCESSED:
        return
    if invoice.route_target != ROUTE_TEAM:
        return
    if not counts_toward_spend(invoice.team_expense_kind):
        return

    employees = await list_employee_masters(session, invoice.tenant_id)
    employee = resolve_team_expense_employee(
        employees,
        employee_email=getattr(invoice, "employee_email", None),
        email_sender=invoice.email_sender,
    )
    if employee is None:
        return

    # Ensure stamp for future lookups.
    canonical = normalize_employee_email(employee.email)
    if canonical and not (invoice.employee_email or "").strip():
        invoice.employee_email = canonical

    row = await get_employee_master_by_id(session, invoice.tenant_id, employee.id)
    if row is None:
        return

    await rebuild_employee_spend_cache(
        session,
        invoice.tenant_id,
        row,
        as_of=invoice.invoice_date or date.today(),
    )
    row.claim_count = (row.claim_count or 0) + 1
    row.last_claim = (invoice.invoice_date or date.today()).isoformat()
    await session.flush()
    await sync_masters_to_config_file(session, invoice.tenant_id)
