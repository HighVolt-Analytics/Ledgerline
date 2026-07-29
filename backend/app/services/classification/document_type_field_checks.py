"""Presence checks for parsed invoice fields used in DT completeness scoring."""

from __future__ import annotations

from decimal import Decimal

from app.models.invoice import Invoice
from app.services.classification.document_type_rule_engine import DocumentClassifierContext
from app.services.invoice.invoice_data import InvoiceData
from app.services.purchase.po_reference import is_plausible_po_reference


def _invoice_po(invoice: Invoice, parsed: InvoiceData) -> str:
    return (parsed.po_reference or invoice.po_reference or "").strip()


def _line_items_amount_sum(parsed: InvoiceData) -> Decimal | None:
    if not parsed.line_items:
        return None
    total = Decimal("0")
    saw_amount = False
    for line in parsed.line_items:
        if line.amount is not None:
            total += line.amount
            saw_amount = True
        elif line.qty is not None and line.unit_price is not None:
            total += line.qty * line.unit_price
            saw_amount = True
    return total if saw_amount else None


def _numeric_field_present(
    key: str,
    *,
    invoice: Invoice,
    parsed: InvoiceData,
) -> bool:
    from app.services.extraction.extraction_field_values import read_extraction_field_value

    if key == "total":
        if parsed.total is not None or invoice.total is not None:
            return True
    elif key == "subtotal":
        if parsed.subtotal is not None or invoice.subtotal is not None:
            return True
    else:
        return False

    extracted = read_extraction_field_value(key, invoice=invoice, parsed=parsed)
    if extracted:
        return True

    line_sum = _line_items_amount_sum(parsed)
    if line_sum is not None and line_sum > 0:
        return True

    if key == "total" and parsed.subtotal is not None and parsed.gst is not None:
        return True
    if key == "total" and invoice.subtotal is not None and invoice.gst is not None:
        return True
    return False


def field_is_present(
    field_key: str,
    *,
    invoice: Invoice,
    parsed: InvoiceData,
    ctx: DocumentClassifierContext,
) -> bool:
    key = field_key.strip().lower()
    if key == "vendor":
        return bool(ctx.vendor)
    if key == "invoice_no":
        return bool(ctx.invoice_no)
    if key == "po_reference":
        po = _invoice_po(invoice, parsed)
        return bool(po and is_plausible_po_reference(po))
    if key == "total":
        return _numeric_field_present("total", invoice=invoice, parsed=parsed)
    if key == "subtotal":
        return _numeric_field_present("subtotal", invoice=invoice, parsed=parsed)
    if key == "gst":
        return parsed.gst is not None or invoice.gst is not None
    if key == "abn":
        return bool((parsed.abn or invoice.abn or "").strip())
    if key == "invoice_date":
        return parsed.invoice_date is not None or invoice.invoice_date is not None
    if key == "due_date":
        return parsed.due_date is not None or invoice.due_date is not None
    if key == "line_items":
        return bool(parsed.line_items)
    if key == "bank_details":
        return bool(
            (parsed.bank_bsb or invoice.bank_bsb or "").strip()
            or (parsed.bank_account or invoice.bank_account or "").strip()
        )
    if key == "attachment_name":
        from pathlib import Path

        attach = ctx.attachment_name or (invoice.email_attachment_name or "").strip()
        if not attach:
            raw_path = (getattr(invoice, "raw_file_path", None) or "").strip()
            if raw_path:
                attach = Path(raw_path).name.strip()
        return bool(attach)
    if key == "cost_centre":
        return bool((parsed.cost_centre or invoice.cost_centre or "").strip())
    if key == "billing_address":
        return bool((invoice.billing_address or "").strip())
    if key == "email_subject":
        return bool((invoice.email_subject or "").strip())
    if key == "email_sender":
        return bool((invoice.email_sender or "").strip())
    if key == "account_code":
        return bool((invoice.account_code or "").strip())
    if key == "account_name":
        return bool((invoice.account_name or "").strip())
    if key == "document_text":
        return bool(ctx.document_text.strip())
    if key == "document_heading":
        return bool(ctx.document_heading.strip())
    from app.services.extraction.extraction_field_values import read_extraction_field_value

    custom_val = read_extraction_field_value(
        key,
        invoice=invoice,
        parsed=parsed,
        document_heading=ctx.document_heading,
    )
    if custom_val:
        return True
    for source in (parsed, invoice):
        if hasattr(source, key):
            val = getattr(source, key, None)
            if val is not None and str(val).strip():
                return True
    return False


def field_is_absent(
    field_key: str,
    *,
    invoice: Invoice,
    parsed: InvoiceData,
    ctx: DocumentClassifierContext,
) -> bool:
    return not field_is_present(
        field_key,
        invoice=invoice,
        parsed=parsed,
        ctx=ctx,
    )
