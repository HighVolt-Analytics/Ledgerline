"""Resolve invoice subtotal/gst/total for posting and reconciliation."""

from __future__ import annotations

from decimal import Decimal

from app.models.invoice import Invoice
from app.services.shared.amount_sanity import plausible_money


def _line_items_subtotal(invoice: Invoice) -> Decimal | None:
    items = invoice.line_items or []
    if not items:
        return None
    total = Decimal("0")
    saw_amount = False
    for line in items:
        if line.amount is not None:
            total += line.amount
            saw_amount = True
        elif line.qty is not None and line.unit_price is not None:
            total += line.qty * line.unit_price
            saw_amount = True
    return total if saw_amount else None


def resolve_invoice_amounts(invoice: Invoice) -> tuple[Decimal, Decimal, Decimal]:
    """Normalize subtotal/gst/total, inferring from line items when headers are missing."""
    gst = invoice.gst if invoice.gst is not None else Decimal("0")
    subtotal = invoice.subtotal
    total = invoice.total

    if subtotal is None:
        subtotal = _line_items_subtotal(invoice)

    if total is None:
        total = (subtotal or Decimal("0")) + gst
    if subtotal is None:
        subtotal = max(total - gst, Decimal("0"))

    return subtotal, gst, total


def backfill_invoice_amounts_from_sources(invoice: Invoice) -> None:
    """Persist inferred header amounts when extraction left totals empty."""
    subtotal, gst, total = resolve_invoice_amounts(invoice)
    if invoice.subtotal is None:
        invoice.subtotal = plausible_money(subtotal)
    if invoice.gst is None and gst != Decimal("0"):
        invoice.gst = plausible_money(gst)
    if invoice.total is None:
        invoice.total = plausible_money(total)


def invoice_payable_total(invoice: Invoice) -> Decimal | None:
    """Amount used for AP reconciliation when invoice.total may be unset."""
    if invoice.total is not None:
        return invoice.total
    _, _, total = resolve_invoice_amounts(invoice)
    if total <= Decimal("0"):
        return None
    return total
