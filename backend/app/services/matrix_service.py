"""Document matrix — flags, payment readiness, and stage metadata."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.schemas.pipeline import MatrixConflictRow


def _parse_validation_results(raw: str | list | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    try:
        data = json.loads(raw)
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _first_validation_failure(inv: Invoice) -> str | None:
    for rule in _parse_validation_results(inv.validation_results):
        if rule.get("skipped"):
            continue
        if not rule.get("passed"):
            message = str(rule.get("message", "")).strip()
            if message:
                return message
            rule_id = str(rule.get("rule", "")).strip()
            return f"Validation rule {rule_id} failed" if rule_id else "Validation failed"
    return None


def derive_matrix_flag(inv: Invoice) -> tuple[str, str | None]:
    """Return matrix flag label and optional human-readable reason."""
    if inv.status == InvoiceStatus.DUPLICATE_SKIPPED:
        return "Duplicate Suspected", _first_validation_failure(inv) or "Duplicate document skipped"
    if inv.status == InvoiceStatus.REJECTED:
        return "Quarantined", "Invoice rejected and quarantined"
    if inv.status == InvoiceStatus.EXCEPTION:
        return "Anomaly Detected", _first_validation_failure(inv) or "Routed to exception review"
    if inv.evaluation_status == "pending_vendor":
        return "Anomaly Detected", "Vendor could not be matched confidently"
    if inv.evaluation_status == "unmatched_expense_vendor":
        if inv.status == InvoiceStatus.PROCESSED:
            return "Clean", None
        return "Anomaly Detected", "Unknown expense vendor under registration threshold"
    if inv.evaluation_status == "needs_review":
        route = inv.route_target or "review"
        return "Anomaly Detected", f"Rule book routing needs review ({route})"
    failure = _first_validation_failure(inv)
    if failure:
        return "Anomaly Detected", failure
    account = (inv.account_name or "").lower()
    if "suspense" in account:
        return "Anomaly Detected", "GL mapping unresolved — routed to suspense"
    return "Clean", None


def derive_matrix_payment_status(inv: Invoice, payment: Payment | None) -> str:
    """Map invoice + payment row to matrix payment badge label."""
    if payment is not None:
        if payment.status == PaymentStatus.PAID:
            return "Paid"
        if payment.status == PaymentStatus.FAILED:
            return "Failed"
        if payment.status == PaymentStatus.AWAITING:
            approvers = payment.approvers or []
            if approvers and all(a.get("state") == "approved" for a in approvers):
                return "Payment Approved"
            return "Awaiting Payment"
        if payment.status in (PaymentStatus.QUEUE, PaymentStatus.SCHEDULED):
            return "Awaiting Payment"

    if inv.status in (
        InvoiceStatus.EXCEPTION,
        InvoiceStatus.DUPLICATE_SKIPPED,
        InvoiceStatus.REJECTED,
    ):
        return "On Hold"
    if inv.evaluation_status in ("needs_review", "pending_vendor", "unmatched_expense_vendor"):
        if inv.status != InvoiceStatus.PROCESSED:
            return "On Hold"
    if inv.status == InvoiceStatus.PROCESSED and inv.due_date is not None:
        return "Awaiting Payment"
    return "—"


from app.services.document_ref_service import display_document_ref


def _document_ref(invoice: Invoice) -> str:
    return display_document_ref(invoice)


def _conflict_detail(inv: Invoice, other: Invoice) -> list[MatrixConflictRow]:
    return [
        MatrixConflictRow(
            field="Vendor",
            this_doc=(inv.vendor or "—").strip() or "—",
            other_doc=(other.vendor or "—").strip() or "—",
        ),
        MatrixConflictRow(
            field="Invoice number",
            this_doc=(inv.invoice_no or "—").strip() or "—",
            other_doc=(other.invoice_no or "—").strip() or "—",
        ),
        MatrixConflictRow(
            field="Total",
            this_doc=str(inv.total or "—"),
            other_doc=str(other.total or "—"),
        ),
        MatrixConflictRow(
            field="Status",
            this_doc=inv.status.value if inv.status else "—",
            other_doc=other.status.value if other.status else "—",
        ),
    ]


async def duplicate_conflict_for_invoice(
    db: AsyncSession,
    tenant_id: int,
    inv: Invoice,
) -> tuple[str | None, list[MatrixConflictRow]]:
    if inv.status != InvoiceStatus.DUPLICATE_SKIPPED:
        return None, []

    from app.models.audit import AuditLog

    original_id: int | None = None
    file_hash: str | None = inv.file_hash
    audit_row = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id == inv.id,
                AuditLog.event == "duplicate_skipped",
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if audit_row and isinstance(audit_row.detail, dict):
        raw_id = audit_row.detail.get("original_invoice_id")
        if isinstance(raw_id, int):
            original_id = raw_id
        if not file_hash and isinstance(audit_row.detail.get("file_hash"), str):
            file_hash = audit_row.detail["file_hash"]

    if original_id is not None:
        other = await db.get(Invoice, original_id)
        if other is not None and other.tenant_id == tenant_id:
            return _document_ref(other), _conflict_detail(inv, other)

    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.id != inv.id,
            Invoice.status != InvoiceStatus.DUPLICATE_SKIPPED,
        )
        .order_by(Invoice.created_at.desc())
    )
    if inv.invoice_no and inv.vendor:
        stmt = stmt.where(
            Invoice.invoice_no == inv.invoice_no,
            Invoice.vendor == inv.vendor,
        )
    elif file_hash:
        stmt = stmt.where(Invoice.file_hash == file_hash)
    else:
        return None, []

    other = (await db.execute(stmt.limit(1))).scalar_one_or_none()
    if other is None:
        return None, []
    return _document_ref(other), _conflict_detail(inv, other)
