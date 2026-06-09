"""Shared types for invoice field extraction."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

ParseSource = Literal["local", "azure_di"]
ParseConfidence = Literal["high", "low"]


@dataclass
class ParsedLineItem:
    description: str | None = None
    qty: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    tax_amount: Decimal | None = None


@dataclass
class InvoiceData:
    vendor: str | None = None
    abn: str | None = None
    invoice_no: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str = "AUD"
    subtotal: Decimal | None = None
    gst: Decimal | None = None
    total: Decimal | None = None
    po_reference: str | None = None
    cost_centre: str | None = None
    line_items: list[ParsedLineItem] = field(default_factory=list)
    raw_fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParseResult:
    data: InvoiceData
    source: ParseSource
    confidence: ParseConfidence
    text_length: int = 0
