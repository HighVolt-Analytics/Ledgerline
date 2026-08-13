"""Shared types for invoice field extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.document_layout import DocumentLayoutResult

ParseSource = Literal["local", "azure_di", "azure_layout"]
ParseConfidence = Literal["high", "low"]
LineItemsGrounding = Literal["grounded", "ungrounded", "unverifiable"]


@dataclass
class ParsedLineItem:
    description: str | None = None
    qty: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    tax_amount: Decimal | None = None
    source: str | None = None
    source_confidence: float | None = None
    fused_from: list[str] | None = None


@dataclass
class InvoiceData:
    vendor: str | None = None
    abn: str | None = None
    billing_address: str | None = None
    bank_bsb: str | None = None
    bank_account: str | None = None
    invoice_no: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str = ""
    subtotal: Decimal | None = None
    gst: Decimal | None = None
    gst_rate: Decimal | None = None
    total: Decimal | None = None
    po_reference: str | None = None
    cost_centre: str | None = None
    line_items: list[ParsedLineItem] = field(default_factory=list)
    line_items_grounding: LineItemsGrounding | None = None
    raw_fields: dict[str, Any] = field(default_factory=dict)
    document_text: str | None = None
    document_heading: str | None = None
    extracted_fields: dict[str, str] = field(default_factory=dict)


@dataclass
class ParseResult:
    data: InvoiceData
    source: ParseSource
    confidence: ParseConfidence
    text_length: int = 0
    layout_hint: str | None = None
    layout: DocumentLayoutResult | None = None


def _attr_if_loaded(obj: object, name: str, default: Any = None) -> Any:
    """Return a column value only when already in the instance dict.

    List/matrix queries defer OCR/JSON columns. Touching an unloaded deferred
    column under async SQLAlchemy raises MissingGreenlet — never trigger that load.
    """
    try:
        from sqlalchemy import inspect as sa_inspect

        state = sa_inspect(obj)
        if name not in state.dict:
            return default
    except Exception:
        pass
    return getattr(obj, name, default)


def _line_items_from_invoice(invoice: object) -> list[ParsedLineItem]:
    """Read line items only when the relationship is already loaded (async-safe)."""
    try:
        from sqlalchemy import inspect as sa_inspect

        if "line_items" in sa_inspect(invoice).unloaded:
            return []
    except Exception:
        pass

    items = getattr(invoice, "line_items", None)
    if items is None:
        return []

    line_items: list[ParsedLineItem] = []
    for line in items:
        fused_raw = getattr(line, "fused_from", None)
        line_items.append(
            ParsedLineItem(
                description=getattr(line, "description", None),
                qty=getattr(line, "qty", None),
                unit_price=getattr(line, "unit_price", None),
                amount=getattr(line, "amount", None),
                tax_amount=getattr(line, "tax_amount", None),
                source=getattr(line, "extraction_source", None),
                source_confidence=(
                    float(line.source_confidence)
                    if getattr(line, "source_confidence", None) is not None
                    else None
                ),
                fused_from=list(fused_raw) if isinstance(fused_raw, list) else None,
            )
        )
    return line_items


def invoice_data_from_invoice(invoice: object) -> InvoiceData:
    """Rebuild parsed field snapshot from a persisted invoice row."""
    return InvoiceData(
        vendor=getattr(invoice, "vendor", None),
        abn=getattr(invoice, "abn", None),
        billing_address=getattr(invoice, "billing_address", None),
        bank_bsb=getattr(invoice, "bank_bsb", None),
        bank_account=getattr(invoice, "bank_account", None),
        invoice_no=getattr(invoice, "invoice_no", None),
        invoice_date=getattr(invoice, "invoice_date", None),
        due_date=getattr(invoice, "due_date", None),
        currency=(getattr(invoice, "currency", None) or "").strip(),
        subtotal=getattr(invoice, "subtotal", None),
        gst=getattr(invoice, "gst", None),
        gst_rate=getattr(invoice, "gst_rate", None),
        total=getattr(invoice, "total", None),
        po_reference=getattr(invoice, "po_reference", None),
        cost_centre=getattr(invoice, "cost_centre", None),
        line_items=_line_items_from_invoice(invoice),
        document_text=_attr_if_loaded(invoice, "document_text"),
        document_heading=_resolved_document_heading(invoice=invoice, parsed=None),
        extracted_fields=dict(_attr_if_loaded(invoice, "extracted_fields") or {}),
    )


def _resolved_document_heading(
    *,
    invoice: object | None,
    parsed: InvoiceData | None,
) -> str | None:
    if parsed is not None and parsed.document_heading:
        return parsed.document_heading
    if invoice is not None:
        heading = getattr(invoice, "document_heading", None)
        if heading:
            return str(heading).strip() or None
    text = None
    if parsed is not None and parsed.document_text:
        text = parsed.document_text
    elif invoice is not None:
        text = _attr_if_loaded(invoice, "document_text")
    if text:
        from app.services.extraction.document_heading_utils import extract_document_heading_signals

        signals = extract_document_heading_signals(text)
        return signals.primary_label
    return None
