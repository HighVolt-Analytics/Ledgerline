"""Canonical extraction routes for finance documents."""

from __future__ import annotations

from enum import StrEnum


class ExtractionRoute(StrEnum):
    INVOICE = "invoice"
    CREDIT_NOTE = "credit_note"
    DEBIT_NOTE = "debit_note"
    RECEIPT = "receipt"
    PURCHASE_ORDER = "purchase_order"
    GRN = "grn"
    STATEMENT = "statement"
    REMITTANCE = "remittance"
    EXPENSE_CLAIM = "expense_claim"
    SUPPORTING_DOCUMENT = "supporting_document"
    UNKNOWN = "unknown"


INVOICE_FAMILY_ROUTES = frozenset(
    {
        ExtractionRoute.INVOICE,
        ExtractionRoute.CREDIT_NOTE,
        ExtractionRoute.DEBIT_NOTE,
    }
)

LAYOUT_PRIMARY_ROUTES = frozenset(
    {
        ExtractionRoute.PURCHASE_ORDER,
        ExtractionRoute.GRN,
        ExtractionRoute.STATEMENT,
        ExtractionRoute.REMITTANCE,
    }
)

LAYOUT_ONLY_ROUTES = frozenset(
    {
        ExtractionRoute.SUPPORTING_DOCUMENT,
        ExtractionRoute.UNKNOWN,
    }
)
