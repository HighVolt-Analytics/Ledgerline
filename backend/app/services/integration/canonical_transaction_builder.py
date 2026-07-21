"""Build canonical accounting transactions from LedgerLink invoices."""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.canonical_accounting_transaction import (
    CanonicalAccountingTransaction,
    CanonicalAttachment,
    CanonicalLine,
    CanonicalSupplier,
    CanonicalTracking,
    PAYLOAD_VERSION,
    build_idempotency_key,
    compute_payload_hash,
    new_qll_transaction_id,
    validate_canonical_totals,
)


class CanonicalTransactionError(ValueError):
    def __init__(self, message: str, *, code: str = "canonical_invalid") -> None:
        super().__init__(message)
        self.code = code


def _safe_filename(name: str | None, *, fallback: str) -> str:
    raw = (name or "").strip() or fallback
    cleaned = re.sub(r"[^\w.\- ()]+", "_", raw).strip("._ ") or fallback
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"
    return cleaned[:180]


async def load_invoice_for_export(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
) -> Invoice:
    invoice = (
        await db.execute(
            select(Invoice)
            .options(selectinload(Invoice.line_items))
            .where(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if invoice is None:
        raise CanonicalTransactionError("Invoice not found", code="invoice_not_found")
    return invoice


def build_canonical_supplier_invoice(
    invoice: Invoice,
    *,
    tenant_id: uuid.UUID,
    qll_transaction_id: str | None = None,
    external_xero_contact_id: str | None = None,
    mapped_account_code: str | None = None,
    mapped_tax_type: str | None = None,
    tracking: list[CanonicalTracking] | None = None,
) -> CanonicalAccountingTransaction:
    """Create a serialisable canonical supplier invoice before any Xero adapter runs."""
    if invoice.tenant_id != tenant_id:
        raise CanonicalTransactionError(
            "Invoice does not belong to this tenant",
            code="tenant_mismatch",
        )
    if invoice.status != InvoiceStatus.PROCESSED:
        raise CanonicalTransactionError(
            "Invoice must be processed before export",
            code="invoice_not_processed",
        )

    txn_id = qll_transaction_id or new_qll_transaction_id(
        tenant_id=tenant_id,
        source_invoice_id=invoice.id,
    )
    account_code = (mapped_account_code or invoice.account_code or "").strip() or None
    tax_code = None
    if invoice.gst is not None and Decimal(str(invoice.gst)) != 0:
        tax_code = f"GST:{invoice.gst_rate}" if invoice.gst_rate is not None else "GST"

    lines: list[CanonicalLine] = []
    line_items = invoice.__dict__.get("line_items")
    if line_items is None:
        line_items = []
    for item in line_items:
        qty = Decimal(str(item.qty)) if item.qty is not None else Decimal("1")
        unit = (
            Decimal(str(item.unit_price))
            if item.unit_price is not None
            else (Decimal(str(item.amount)) if item.amount is not None else Decimal("0"))
        )
        amount = Decimal(str(item.amount)) if item.amount is not None else (qty * unit)
        lines.append(
            CanonicalLine(
                line_id=str(item.id or len(lines) + 1),
                description=(item.description or "Line item").strip() or "Line item",
                quantity=qty,
                unit_price=unit,
                line_amount=amount,
                qll_gl_account_code=account_code,
                mapped_xero_account_code=mapped_account_code or account_code,
                qll_tax_code=tax_code,
                mapped_xero_tax_type=mapped_tax_type,
                tracking=list(tracking or []),
            )
        )
    if not lines:
        total = Decimal(str(invoice.total or invoice.subtotal or 0))
        lines.append(
            CanonicalLine(
                line_id="1",
                description=(invoice.invoice_no or "Invoice total").strip() or "Invoice total",
                quantity=Decimal("1"),
                unit_price=total,
                line_amount=total,
                qll_gl_account_code=account_code,
                mapped_xero_account_code=mapped_account_code or account_code,
                qll_tax_code=tax_code,
                mapped_xero_tax_type=mapped_tax_type,
                tracking=list(tracking or []),
            )
        )

    attachment = None
    if invoice.raw_file_path:
        filename = _safe_filename(
            invoice.email_attachment_name or Path(invoice.raw_file_path).name,
            fallback=f"invoice-{invoice.id}.pdf",
        )
        attachment = CanonicalAttachment(
            filename=filename,
            storage_locator=invoice.raw_file_path,
            mime_type="application/pdf",
        )

    supplier = CanonicalSupplier(
        qll_supplier_id=str(invoice.storage_vendor_slug or invoice.id),
        legal_name=(invoice.vendor or "").strip() or "Unknown supplier",
        tax_id=(invoice.abn or "").strip() or None,
        email=(invoice.email_sender or "").strip() or None,
        external_xero_contact_id=external_xero_contact_id,
    )

    draft = CanonicalAccountingTransaction(
        qll_transaction_id=txn_id,
        tenant_id=str(tenant_id),
        source_invoice_id=invoice.id,
        source_document_id=invoice.document_ref,
        posting_date=invoice.invoice_date,
        due_date=invoice.due_date,
        currency=(invoice.currency or "AUD").strip().upper(),
        supplier=supplier,
        reference=invoice.po_reference or invoice.so_reference,
        lines=lines,
        subtotal=Decimal(str(invoice.subtotal or 0)),
        tax_total=Decimal(str(invoice.gst or 0)),
        total=Decimal(str(invoice.total or 0)),
        attachment=attachment,
        idempotency_key="pending",
        payload_version=PAYLOAD_VERSION,
        payload_hash="",
    )
    payload_hash = compute_payload_hash(draft)
    draft.payload_hash = payload_hash
    draft.idempotency_key = build_idempotency_key(
        tenant_id=tenant_id,
        source_invoice_id=invoice.id,
        payload_version=PAYLOAD_VERSION,
        payload_hash=payload_hash,
    )
    return draft


def assert_canonical_valid(txn: CanonicalAccountingTransaction) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not txn.supplier.legal_name.strip():
        errors.append(
            {
                "field": "supplier",
                "code": "missing_supplier",
                "message": "Supplier legal name is required",
            }
        )
    if not txn.currency:
        errors.append(
            {
                "field": "currency",
                "code": "missing_currency",
                "message": "Currency is required",
            }
        )
    if not txn.lines:
        errors.append(
            {
                "field": "lines",
                "code": "missing_lines",
                "message": "At least one line item is required",
            }
        )
    errors.extend(validate_canonical_totals(txn))
    return errors
