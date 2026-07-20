"""Post-vision header reconcile: currency + total from lightweight PDF text.

Vision-vaulted docs never enter the OCR / currency-detection stack. Tenant
currency must not linger when the document is ambiguous, and unambiguous
glyphs (₹) / labeled grand totals should correct header LLM mistakes.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models.invoice import Invoice
from app.services.extraction.field_validators import normalize_amount
from app.services.shared.amount_sanity import plausible_money
from app.services.shared.currency import (
    AMBIGUOUS_CURRENCY_SYMBOLS,
    UNAMBIGUOUS_SYMBOL_TO_ISO,
    detect_currency_code_in_text,
    detect_currency_symbol_in_text,
    resolve_currency_from_ocr,
)
from app.services.shared.iso4217_catalog import is_iso4217_currency

_SUBTOTAL_NEAR_AMOUNT = re.compile(
    r"(?is)(?:sub[\s-]*total|total\s+before\s+tax|taxable\s+(?:value|amount)|"
    r"total\s+excluding\s+tax|total\s+excl\.?\s*tax)"
    r"[^\d]{0,48}"
    r"(?P<amt>[\d][\d,]*(?:\.\d{1,4})?)"
)

_GRAND_TOTAL_NEAR_AMOUNT = re.compile(
    r"(?is)(?:grand\s+total|amount\s+(?:due|payable)|net\s+payable|"
    r"total\s+(?:due|payable|amount(?:\s+due)?|incl\.?\s*tax|including\s+tax)|"
    r"(?<![a-z])total(?!\s+(?:before|excluding|excl\.?\s*tax|ex\b)|[\s-]*total))"
    r"[^\d]{0,48}"
    r"(?P<amt>[\d][\d,]*(?:\.\d{1,4})?)"
)

_TAX_NEAR_AMOUNT = re.compile(
    r"(?is)(?:value[\s-]*added\s+tax|vat|gst|sales\s+tax|tax\s+amount|"
    r"igst|cgst|sgst)"
    r"[^\d]{0,48}"
    r"(?P<amt>[\d][\d,]*(?:\.\d{1,4})?)"
)

_PREFIXED_SYMBOL_TO_ISO = {
    "A$": "AUD",
    "AU$": "AUD",
    "AUD$": "AUD",
    "US$": "USD",
    "USD$": "USD",
    "NZ$": "NZD",
    "NZD$": "NZD",
    "C$": "CAD",
    "CA$": "CAD",
    "CAD$": "CAD",
    "S$": "SGD",
    "SG$": "SGD",
    "HK$": "HKD",
    "NT$": "TWD",
    "R$": "BRL",
}

_EPS = Decimal("0.02")


def _parse_money_token(token: str | None) -> Decimal | None:
    if not token:
        return None
    return normalize_amount(token)


def _amounts_from_pattern(pattern: re.Pattern[str], text: str) -> list[Decimal]:
    out: list[Decimal] = []
    for match in pattern.finditer(text or ""):
        money = _parse_money_token(match.group("amt"))
        if money is not None:
            out.append(money)
    return out


def _iso_corroborated_in_text(iso: str, text: str | None) -> bool:
    """True when OCR/text literally supports this ISO (code, prefix, or glyph)."""
    if not iso or not (text or "").strip():
        return False
    code = iso.strip().upper()
    raw = text or ""
    if detect_currency_code_in_text(raw) == code:
        return True
    upper = raw.upper()
    if re.search(rf"(?<![A-Z0-9]){re.escape(code)}(?![A-Z0-9])", upper):
        return True
    for prefix, mapped in _PREFIXED_SYMBOL_TO_ISO.items():
        if mapped == code and prefix.lower() in raw.lower():
            return True
    symbol = detect_currency_symbol_in_text(raw)
    if symbol and UNAMBIGUOUS_SYMBOL_TO_ISO.get(symbol) == code:
        return True
    return False


def reconcile_currency_from_text(
    *,
    current_currency: str | None,
    text: str | None,
) -> tuple[str, str | None, str]:
    """Return (iso_or_empty, currency_symbol_or_none, reason).

    Unambiguous OCR evidence wins over a wrong vision ISO. Ungrounded ISO
    codes (e.g. invented AUD on bare ``$``) are cleared so the UI asks the user.
    """
    current = (current_currency or "").strip().upper()
    if current and not is_iso4217_currency(current):
        current = ""

    iso, symbol = resolve_currency_from_ocr(text, existing_currency=None)
    if iso:
        if current and current != iso:
            return iso, None, f"ocr_override_{current}_to_{iso}"
        if not current:
            return iso, None, f"ocr_fill_{iso}"
        return current, None, "ocr_confirms_iso"

    if symbol and symbol in AMBIGUOUS_CURRENCY_SYMBOLS:
        if current and _iso_corroborated_in_text(current, text):
            return current, None, "keep_corroborated_vision_iso"
        # Bare $ / ¥ with no ISO corroboration — never keep a guessed code.
        return "", symbol, "cleared_uncorroborated_iso" if current else f"ambiguous_symbol_{symbol}"

    if symbol:
        return current, symbol, "symbol_only"

    if current and _iso_corroborated_in_text(current, text):
        return current, None, "keep_corroborated_vision_iso"
    if current:
        # Vision invented an ISO with no text support — leave empty for human pick.
        return "", None, "cleared_ungrounded_iso"
    return "", None, "empty"


def prefer_grand_total_over_subtotal(
    current: Decimal | None,
    text: str | None,
) -> tuple[Decimal | None, str]:
    """If ``current`` matches a labeled subtotal, prefer a labeled grand total."""
    if current is None or not (text or "").strip():
        return current, "unchanged"

    subtotals = _amounts_from_pattern(_SUBTOTAL_NEAR_AMOUNT, text or "")
    totals = _amounts_from_pattern(_GRAND_TOTAL_NEAR_AMOUNT, text or "")
    taxes = _amounts_from_pattern(_TAX_NEAR_AMOUNT, text or "")

    matches_subtotal = any((s - current).copy_abs() <= _EPS for s in subtotals)
    if not matches_subtotal:
        return current, "unchanged"

    for total in totals:
        if (total - current).copy_abs() <= _EPS:
            continue
        for tax in taxes:
            if (current + tax - total).copy_abs() <= _EPS:
                return total, "upgraded_subtotal_plus_tax"
        return total, "upgraded_labeled_grand_total"

    for tax in taxes:
        candidate = current + tax
        try:
            plausible = plausible_money(candidate)
        except (InvalidOperation, ValueError, TypeError):
            plausible = None
        if plausible is not None and (plausible - current).copy_abs() > _EPS:
            return plausible, "upgraded_subtotal_plus_tax_arith"

    return current, "unchanged"


def apply_vision_header_text_reconcile(
    invoice: Invoice,
    text: str | None,
) -> dict[str, Any]:
    """Mutate invoice currency/total from lightweight PDF text. Returns audit detail."""
    detail: dict[str, Any] = {
        "currency_before": (invoice.currency or "").strip().upper() or None,
        "total_before": str(invoice.total) if invoice.total is not None else None,
        "currency_reason": "skipped",
        "total_reason": "skipped",
        "text_chars": len((text or "").strip()),
    }
    if not (text or "").strip():
        return detail

    iso, symbol, ccy_reason = reconcile_currency_from_text(
        current_currency=invoice.currency,
        text=text,
    )
    detail["currency_reason"] = ccy_reason
    invoice.currency = iso
    fields = dict(invoice.extracted_fields or {})
    if iso:
        fields.pop("currency_symbol", None)
        fields["currency"] = iso
    else:
        fields.pop("currency", None)
        if symbol:
            fields["currency_symbol"] = symbol
        else:
            fields.pop("currency_symbol", None)
    invoice.extracted_fields = fields
    detail["currency_after"] = iso or None
    detail["currency_symbol"] = symbol

    money, total_reason = prefer_grand_total_over_subtotal(invoice.total, text)
    detail["total_reason"] = total_reason
    if money is not None and money != invoice.total:
        invoice.total = money
        fields = dict(invoice.extracted_fields or {})
        fields["total"] = format(money, "f")
        invoice.extracted_fields = fields
    detail["total_after"] = str(invoice.total) if invoice.total is not None else None
    return detail
