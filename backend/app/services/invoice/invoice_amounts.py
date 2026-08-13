"""Resolve invoice subtotal/gst/total for posting and reconciliation."""

from __future__ import annotations

from decimal import Decimal

from app.models.invoice import Invoice
from app.services.shared.amount_sanity import plausible_money

# Paise / cent tolerance when judging line sums vs header identity.
_AMOUNT_EPS = Decimal("0.05")


def _line_amount(line: object) -> Decimal | None:
    amount = getattr(line, "amount", None)
    if amount is not None:
        return amount
    qty = getattr(line, "qty", None)
    unit_price = getattr(line, "unit_price", None)
    if qty is not None and unit_price is not None:
        return qty * unit_price
    return None


def _is_non_expense_line(line: object) -> bool:
    """Tax / summary / metadata rows must not feed expense subtotal."""
    from app.services.extraction.line_item_skip_patterns import should_skip_line_row

    return should_skip_line_row(getattr(line, "description", None))


def _line_items_subtotal(invoice: Invoice) -> Decimal | None:
    """Sum product/service lines only — exclude CGST/SGST/IGST and other summary rows."""
    items = invoice.line_items or []
    if not items:
        return None
    total = Decimal("0")
    saw_amount = False
    for line in items:
        if _is_non_expense_line(line):
            continue
        amount = _line_amount(line)
        if amount is None:
            continue
        total += amount
        saw_amount = True
    return total if saw_amount else None


def resolve_invoice_amounts(invoice: Invoice) -> tuple[Decimal, Decimal, Decimal]:
    """Normalize subtotal/gst/total for journal posting.

    Priority when header subtotal is missing:
    1. ``total − gst`` when both total and gst are present (AP / tax / expense identity)
    2. Sum of non-tax line items
    3. ``total − gst`` / zero as last resort

    Tax breakdown rows (CGST/SGST/IGST, etc.) never contribute to expense subtotal.
    """
    gst = invoice.gst if invoice.gst is not None else Decimal("0")
    subtotal = invoice.subtotal
    total = invoice.total

    if (
        subtotal is not None
        and total is not None
        and (subtotal + gst - total).copy_abs() > _AMOUNT_EPS
    ):
        line_sub = _line_items_subtotal(invoice)
        if line_sub is not None and (line_sub + gst - total).copy_abs() <= _AMOUNT_EPS:
            subtotal = line_sub
        elif invoice.gst is not None:
            subtotal = max(total - gst, Decimal("0"))
        elif line_sub is not None:
            subtotal = line_sub
        else:
            subtotal = max(total - gst, Decimal("0"))

    if subtotal is None:
        if total is not None and invoice.gst is not None:
            # Finance identity for accrual: Cr AP = total, Dr tax = gst,
            # Dr expense = total − gst. Prefer this over tax-inclusive line dumps.
            subtotal = max(total - gst, Decimal("0"))
        else:
            subtotal = _line_items_subtotal(invoice)

    if total is None:
        total = (subtotal or Decimal("0")) + gst
    if subtotal is None:
        subtotal = max((total or Decimal("0")) - gst, Decimal("0"))

    return subtotal, gst, total


def backfill_invoice_amounts_from_sources(invoice: Invoice) -> None:
    """Persist inferred header amounts when extraction left totals empty."""
    if invoice.total is None and invoice.subtotal is None:
        return
    subtotal, gst, total = resolve_invoice_amounts(invoice)
    if invoice.subtotal is None:
        invoice.subtotal = plausible_money(subtotal)
    if invoice.gst is None:
        # Persist 0 when the print has a total but no tax line — otherwise DT
        # required gst/subtotal stay "missing" forever.
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


def amounts_look_tax_inclusive_subtotal(
    *,
    subtotal: Decimal | None,
    gst: Decimal | None,
    total: Decimal | None,
) -> bool:
    """True when subtotal ≈ total while a positive gst exists (tax double-count risk)."""
    if subtotal is None or total is None or gst is None:
        return False
    if gst <= 0:
        return False
    return (subtotal - total).copy_abs() <= _AMOUNT_EPS
