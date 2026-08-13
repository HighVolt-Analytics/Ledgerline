"""Detect missing Fields blockers before blaming Suspense GL."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Literal

from app.models.invoice import Invoice

InvoiceBlockerKey = Literal["currency", "total", "vendor"]

_TRIAD: tuple[InvoiceBlockerKey, ...] = ("currency", "total", "vendor")


def is_invoice_currency_set(currency: str | None) -> bool:
    """True when currency is a valid ISO 4217 alpha-3 code."""
    code = (currency or "").strip().upper()
    return bool(code) and len(code) == 3 and code.isalpha()


def is_total_present(inv: Invoice) -> bool:
    if inv.total is None:
        return False
    try:
        return Decimal(str(inv.total)) > 0
    except Exception:
        return False


def detect_invoice_blockers(
    inv: Invoice,
    *,
    configured_keys: Sequence[str] | None = None,
) -> list[InvoiceBlockerKey]:
    """Missing Fields blockers from invoice columns (list-safe).

    Only vendor/total/currency keys that the DT actually lists are checked.
    ``None`` or empty means the DT did not configure those keys — do not invent them.
    """
    wanted = {str(k).strip().lower() for k in (configured_keys or []) if str(k).strip()}
    check = {key for key in _TRIAD if key in wanted}
    blockers: list[InvoiceBlockerKey] = []
    if "currency" in check and not is_invoice_currency_set(inv.currency):
        blockers.append("currency")
    if "total" in check and not is_total_present(inv):
        blockers.append("total")
    if "vendor" in check and not (inv.vendor or "").strip():
        blockers.append("vendor")
    return blockers


_BLOCKER_LABEL: dict[InvoiceBlockerKey, str] = {
    "currency": "currency",
    "total": "total",
    "vendor": "vendor",
}


def blocker_issue_title(blockers: list[InvoiceBlockerKey]) -> str | None:
    if not blockers:
        return None
    if len(blockers) == 1:
        only = blockers[0]
        if only == "currency":
            return "Currency not extracted"
        if only == "total":
            return "Total not extracted"
        return "Vendor not extracted"
    labels = [_BLOCKER_LABEL[key] for key in blockers]
    return f"Financial fields incomplete — {', '.join(labels)}"


def blocker_fix_hint(blockers: list[InvoiceBlockerKey]) -> str | None:
    if not blockers:
        return None
    if len(blockers) == 1:
        only = blockers[0]
        if only == "currency":
            return "Fields tab — select currency, then save and continue"
        if only == "total":
            return "Fields tab — enter total (and tax if needed), then continue"
        return "Fields tab — enter vendor name, then save and continue"
    return "Fields tab — complete currency, total, and line items, then Confirm & process"


def blocker_hold_reason(blockers: list[InvoiceBlockerKey]) -> str | None:
    """Issue-style reason with a short action (flag_reason / Validated detail)."""
    if not blockers:
        return None
    if len(blockers) == 1:
        only = blockers[0]
        if only == "currency":
            return "Currency not extracted — select on Fields"
        if only == "total":
            return "Total not extracted — enter on Fields"
        return "Vendor not extracted — enter on Fields"
    labels = [_BLOCKER_LABEL[key] for key in blockers]
    return f"Financial fields incomplete — {', '.join(labels)} — complete on Fields"
