"""Shared vision header-extract field contract (prompt, parse, API, UI).

Single source of truth — do not duplicate key lists in frontend or clients.
"""

from __future__ import annotations

# JSON keys the vision header LLM must return (order matches prompt).
VISION_HEADER_JSON_KEYS: tuple[str, ...] = (
    "document_heading",
    "canonical_document_type",
    "counterparty_name",
    "perspective",
    "invoice_no",
    "proforma_invoice_no",
    "po_reference",
    "so_reference",
    "other_reference",
    "invoice_date",
    "total",
    "currency",
    "confidence",
    "reason",
)

# Invoice columns / Fields-tab keys after persist (counterparty_name → vendor).
VISION_HEADER_PERSISTED_FIELD_KEYS: tuple[str, ...] = (
    "document_heading",
    "vendor",
    "invoice_no",
    "proforma_invoice_no",
    "invoice_date",
    "total",
    "currency",
    "po_reference",
    "so_reference",
    "other_reference",
)

# Stale DB seed detection — active body must include these (hardened prompt markers).
VISION_HEADER_PROMPT_MARKERS: tuple[str, ...] = (
    "invoice_date",
    "total",
    "currency",
    "proforma_invoice_no",
    "Never copy a purchase-order number into so_reference",
    "GENERAL EXTRACTION PRINCIPLE",
    "MULTI-PARTY DISAMBIGUATION",
    "TOTAL DISAMBIGUATION",
    "MULTI-PAGE / WHOLE-PDF HANDLING",
    "Merge evidence across ALL pages",
    "EVERY finance document kind",
    "invoice_no — ONLY when clearly labeled as an invoice number",
    "NEVER put Permit No / Clearance No / Declaration No / Document No",
    "never put an adjacent column HEADER into invoice_no",
    "Never invent AUD/USD when ₹ is printed",
    "you MUST return the after-tax Total",
    "SELF-CHECK BEFORE RETURNING OUTPUT",
    "An empty string is always a safer output",
    # Non-finance titled docs (handover / LOA) must still get a vault type name.
    "Supporting / ops / legal titles still get a canonical_document_type",
    "Handover Slip / HANDOVER SLIP → \"Handover Slip\"",
)

# Common LLM aliases → canonical JSON key (first match wins).
VISION_HEADER_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "invoice_date": (
        "invoice_date",
        "invoiceDate",
        "document_date",
        "documentDate",
        "date",
        "issue_date",
        "issueDate",
    ),
    "total": (
        "total",
        "grand_total",
        "grandTotal",
        "amount_due",
        "amountDue",
        "total_amount",
        "totalAmount",
        "invoice_total",
        "invoiceTotal",
    ),
    "currency": ("currency", "currency_code", "currencyCode", "ccy"),
    "counterparty_name": (
        "counterparty_name",
        "counterpartyName",
        "counterparty",
        "vendor_name",
        "vendorName",
        "supplier_name",
        "supplierName",
        "customer_name",
        "customerName",
    ),
    "document_heading": (
        "document_heading",
        "documentHeading",
        "heading",
        "title",
        "document_title",
        "documentTitle",
    ),
    "canonical_document_type": (
        "canonical_document_type",
        "canonicalDocumentType",
        "document_type",
        "documentType",
    ),
    "invoice_no": ("invoice_no", "invoiceNo", "invoice_number", "invoiceNumber"),
    "proforma_invoice_no": (
        "proforma_invoice_no",
        "proformaInvoiceNo",
        "proforma_invoice_number",
        "proformaInvoiceNumber",
        "proforma_no",
        "proformaNo",
        "pro_forma_invoice_no",
        "proFormaInvoiceNo",
    ),
    "po_reference": ("po_reference", "poReference", "po_number", "poNumber", "purchase_order"),
    "so_reference": ("so_reference", "soReference", "so_number", "soNumber", "sales_order"),
    "other_reference": ("other_reference", "otherReference", "reference", "ref"),
}


def vision_header_json_keys_csv() -> str:
    """Comma-separated keys for the system prompt Return-JSON line."""
    return ", ".join(VISION_HEADER_JSON_KEYS)
