"""Presence checks for parsed invoice fields used in DT completeness scoring."""

from __future__ import annotations

from app.models.invoice import Invoice
from app.services.document_type_rule_engine import DocumentClassifierContext
from app.services.invoice_data import InvoiceData
from app.services.po_reference import is_plausible_po_reference


def _invoice_po(invoice: Invoice, parsed: InvoiceData) -> str:
    return (parsed.po_reference or invoice.po_reference or "").strip()


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
        return parsed.total is not None or invoice.total is not None
    if key == "subtotal":
        return parsed.subtotal is not None or invoice.subtotal is not None
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
        return bool(
            ctx.attachment_name or (invoice.email_attachment_name or "").strip()
        )
    if key == "cost_centre":
        return bool((parsed.cost_centre or invoice.cost_centre or "").strip())
    if key == "billing_address":
        return bool((invoice.billing_address or "").strip())
    if key == "email_subject":
        return bool((invoice.email_subject or "").strip())
    if key == "account_code":
        return bool((invoice.account_code or "").strip())
    if key == "account_name":
        return bool((invoice.account_name or "").strip())
    if key == "document_text":
        return bool(ctx.document_text.strip())
    if key == "document_heading":
        return bool(ctx.document_heading.strip())
    from app.services.extraction_field_values import read_extraction_field_value

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
