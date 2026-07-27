"""Build and validate Xero ACCPAY Draft payloads from canonical transactions."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.schemas.canonical_accounting_transaction import CanonicalAccountingTransaction

XERO_STATUS_DRAFT = "DRAFT"
XERO_TYPE_ACCPAY = "ACCPAY"


def build_accpay_draft_payload(
    txn: CanonicalAccountingTransaction,
    *,
    contact_id: str,
    line_amount_types: str = "Exclusive",
) -> dict[str, Any]:
    """Build ACCPAY DRAFT invoice body for POST /Invoices."""
    line_items: list[dict[str, Any]] = []
    for line in txn.lines:
        item: dict[str, Any] = {
            "Description": line.description,
            "Quantity": float(line.quantity),
            "UnitAmount": float(line.unit_price),
            "AccountCode": line.mapped_xero_account_code,
        }
        if line.line_amount is not None:
            item["LineAmount"] = float(line.line_amount)
        if line.mapped_xero_tax_type:
            item["TaxType"] = line.mapped_xero_tax_type
        tracking = []
        for track in line.tracking:
            if track.mapped_xero_tracking_category_id and track.mapped_xero_tracking_option_id:
                tracking.append(
                    {
                        "TrackingCategoryID": track.mapped_xero_tracking_category_id,
                        "TrackingOptionID": track.mapped_xero_tracking_option_id,
                        "Name": track.category_name,
                        "Option": track.option_name,
                    }
                )
        if tracking:
            item["Tracking"] = tracking
        line_items.append(item)

    payload: dict[str, Any] = {
        "Type": XERO_TYPE_ACCPAY,
        "Contact": {"ContactID": contact_id},
        "LineAmountTypes": line_amount_types,
        "LineItems": line_items,
        "Status": XERO_STATUS_DRAFT,
        "CurrencyCode": txn.currency,
        "Reference": f"QLL:{txn.qll_transaction_id}",
    }
    # Prefer stable LedgerLink invoice number when present.
    # Reference carries the QLL transaction id for idempotent evidence.
    invoice_number = None
    # source document / invoice no is not on txn directly beyond reference;
    # callers may set InvoiceNumber separately via optional field on metadata.
    if txn.source_document_id:
        invoice_number = txn.source_document_id
    if invoice_number:
        payload["InvoiceNumber"] = str(invoice_number)[:255]
    if txn.posting_date:
        payload["Date"] = txn.posting_date.isoformat()
    if txn.due_date:
        payload["DueDate"] = txn.due_date.isoformat()
    return payload


def assert_draft_status(payload: dict[str, Any]) -> None:
    if payload.get("Status") != XERO_STATUS_DRAFT:
        raise ValueError("All Phase-1 Xero exports must use Status=DRAFT")
    if payload.get("Type") != XERO_TYPE_ACCPAY:
        raise ValueError("Phase-1 export only supports ACCPAY supplier bills")


def validate_accpay_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if payload.get("Type") != XERO_TYPE_ACCPAY:
        errors.append(
            {
                "field": "Type",
                "code": "accrec_not_supported",
                "message": "Only ACCPAY supplier bills are supported in Phase 1",
            }
        )
    if payload.get("Status") != XERO_STATUS_DRAFT:
        errors.append(
            {
                "field": "Status",
                "code": "invalid_payload",
                "message": "Export status must be DRAFT",
            }
        )
    contact = payload.get("Contact") or {}
    if not contact.get("ContactID"):
        errors.append(
            {
                "field": "ContactID",
                "code": "contact_not_mapped",
                "message": "supplier has no Xero contact",
            }
        )
    for idx, line in enumerate(payload.get("LineItems") or []):
        if not line.get("AccountCode"):
            errors.append(
                {
                    "field": f"LineItems[{idx}].AccountCode",
                    "code": "account_not_mapped",
                    "message": "GL account not mapped",
                }
            )
        if line.get("TaxType") is None and False:
            pass
    if not payload.get("CurrencyCode"):
        errors.append(
            {
                "field": "CurrencyCode",
                "code": "currency_missing",
                "message": "Organisation currency is not configured",
            }
        )
    return errors


def money(value: Decimal | float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value)
