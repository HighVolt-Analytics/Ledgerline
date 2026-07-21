"""Post-vision header reconcile: currency + total + grounding from PDF text.

Vision-vaulted docs never enter the OCR / currency-detection stack. Tenant
currency must not linger when the document is ambiguous, and unambiguous
glyphs (₹) / labeled grand totals should correct header LLM mistakes.
When local PDF text is rich enough, ungrounded header strings/dates/totals
are cleared so inventeds do not reach the vault.
"""

from __future__ import annotations

import re
from dataclasses import replace
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

# Below this, treat text as scan/incomplete — do not clear vision values.
_MIN_TEXT_CHARS_FOR_GROUNDING = 80

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


def text_usable_for_header_grounding(text: str | None) -> bool:
    return len((text or "").strip()) >= _MIN_TEXT_CHARS_FOR_GROUNDING


def _invoice_no_soft_grounded(value: str, text: str) -> bool:
    """True when invoice_no (or its digit run) appears in PDF text."""
    from app.services.extraction.field_grounding_service import (
        _invoice_no_grounded,
        value_grounded_in_ocr,
    )
    from app.services.extraction.invoice_no_sanitizer import sanitize_invoice_no

    if _invoice_no_grounded(value, text):
        return True
    clean = sanitize_invoice_no(value) or str(value).strip()
    if clean and value_grounded_in_ocr(clean, text, field_key="invoice_no"):
        return True
    digits = "".join(c for c in clean if c.isdigit())
    if len(digits) >= 6 and re.search(rf"(?<!\d){re.escape(digits)}(?!\d)", text or ""):
        return True
    # Permit-style alnum IDs (e.g. OD5I458006S) — ignore O/0 I/1 confusions lightly
    compact = re.sub(r"[^A-Z0-9]", "", clean.upper())
    text_compact = re.sub(r"[^A-Z0-9]", "", (text or "").upper())
    if len(compact) >= 6 and compact in text_compact:
        return True
    return False


def _recover_invoice_no_from_text(text: str | None) -> str:
    from app.services.extraction.invoice_no_sanitizer import extract_invoice_no_from_text

    return (extract_invoice_no_from_text(text or "") or "").strip()


_PERMIT_NO_LINE = re.compile(
    r"(?im)(?:Permit\s*(?:No\.?|Number|#))\s*[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})"
)
_UNIQUE_REF_LINE = re.compile(
    r"(?im)(?:Unique\s*Ref(?:erence)?)\s*[:\s#]*([A-Z0-9][A-Z0-9\-/\s]{4,80})"
)


def _recover_permit_no_from_text(text: str | None) -> str:
    match = _PERMIT_NO_LINE.search(text or "")
    if not match:
        return ""
    from app.services.extraction.invoice_no_sanitizer import sanitize_invoice_no

    return (sanitize_invoice_no(match.group(1)) or "").strip()


def _normalize_other_reference(value: str | None) -> str:
    token = re.sub(r"\s+", " ", str(value or "").strip())
    return token[:128]


def _looks_like_unique_ref_blob(value: str | None) -> bool:
    """True for Singapore Unique Ref style tokens (id + yyyymmdd + seq)."""
    token = _normalize_other_reference(value)
    return bool(re.match(r"^[A-Z0-9]{6,}\s+\d{8}\s+\d{2,}$", token, re.I))


def enrich_vision_header_refs_from_text(
    result: Any,
    text: str | None,
) -> tuple[Any, dict[str, Any]]:
    """Fill invoice_no / other_reference from labeled PDF text when missing.

    Prefer commercial INV NO for invoice_no; keep Permit No in other_reference when
    invoice_no already holds a different commercial number.
    """
    from app.services.invoice.vision_header_extract import VisionHeaderExtractResult

    detail: dict[str, Any] = {"filled": []}
    if not isinstance(result, VisionHeaderExtractResult) or not result.success:
        return result, detail
    if not text_usable_for_header_grounding(text):
        return result, detail

    updates: dict[str, Any] = {}
    inv = (result.invoice_no or "").strip()
    recovered_inv = _recover_invoice_no_from_text(text)
    permit = _recover_permit_no_from_text(text)

    if not inv and recovered_inv:
        updates["invoice_no"] = recovered_inv
        inv = recovered_inv
        detail["filled"].append("invoice_no")

    other = _normalize_other_reference(result.other_reference)
    unique_match = _UNIQUE_REF_LINE.search(text or "")
    unique_ref = _normalize_other_reference(unique_match.group(1) if unique_match else "")

    prefer_permit_as_other = bool(
        permit
        and inv
        and permit.upper() != inv.upper()
        and (
            not other
            or _looks_like_unique_ref_blob(other)
            or (unique_ref and other.upper() == unique_ref.upper())
        )
    )
    if prefer_permit_as_other:
        updates["other_reference"] = permit
        detail["filled"].append("other_reference")
    elif not other and permit and (not inv or permit.upper() != inv.upper()):
        updates["other_reference"] = permit
        detail["filled"].append("other_reference")
    elif not other and unique_ref:
        updates["other_reference"] = unique_ref
        detail["filled"].append("other_reference")

    if not updates:
        return result, detail
    return replace(result, **updates), detail


def ground_vision_header_result(
    result: Any,
    text: str | None,
) -> tuple[Any, dict[str, Any]]:
    """Clear header fields that cannot be verified in local PDF text.

    Skips grounding when text is thin (scans) so vision remains the source of
    truth. ``canonical_document_type`` and ``perspective`` are not grounded —
    they are normalized / inferred labels, not literal page tokens.

    ``invoice_no`` is recovered from labeled PDF text (INV NO / Permit No) when
    vision left it empty or grounding would clear a value that OCR text supports
    under a softer match.
    """
    from app.services.extraction.field_grounding_service import (
        _date_grounded_in_ocr,
        _money_grounded_in_ocr,
        _ocr_money_forms,
        value_grounded_in_ocr,
    )
    from app.services.invoice.vision_header_extract import VisionHeaderExtractResult

    detail: dict[str, Any] = {
        "skipped": False,
        "cleared": [],
        "kept": [],
        "recovered": [],
        "text_chars": len((text or "").strip()),
    }
    if not isinstance(result, VisionHeaderExtractResult) or not result.success:
        detail["skipped"] = True
        detail["reason"] = "no_success_result"
        return result, detail
    if not text_usable_for_header_grounding(text):
        detail["skipped"] = True
        detail["reason"] = "thin_or_empty_text"
        return result, detail

    raw = text or ""
    updates: dict[str, Any] = {}
    cleared: list[str] = []
    kept: list[str] = []
    recovered: list[str] = []

    def _check_str(field: str, value: str, *, field_key: str | None = None) -> str:
        token = (value or "").strip()
        if not token:
            return ""
        ok = value_grounded_in_ocr(token, raw, field_key=field_key or field)
        if ok:
            kept.append(field)
            return token
        cleared.append(field)
        return ""

    updates["document_heading"] = _check_str("document_heading", result.document_heading)
    updates["counterparty_name"] = _check_str(
        "counterparty_name",
        result.counterparty_name,
        field_key="vendor",
    )

    vision_inv = (result.invoice_no or "").strip()
    if vision_inv and _invoice_no_soft_grounded(vision_inv, raw):
        kept.append("invoice_no")
    elif vision_inv:
        # Vision value not corroborated — try labeled text recovery before clearing.
        recovered_inv = _recover_invoice_no_from_text(raw)
        if recovered_inv:
            updates["invoice_no"] = recovered_inv
            recovered.append("invoice_no")
            detail["invoice_no_vision_cleared"] = vision_inv
        else:
            updates["invoice_no"] = ""
            cleared.append("invoice_no")
            detail["invoice_no_vision_cleared"] = vision_inv
    else:
        recovered_inv = _recover_invoice_no_from_text(raw)
        if recovered_inv:
            updates["invoice_no"] = recovered_inv
            recovered.append("invoice_no")

    for field in (
        "proforma_invoice_no",
        "po_reference",
        "so_reference",
        "other_reference",
    ):
        updates[field] = _check_str(field, getattr(result, field), field_key=field)

    if result.invoice_date is not None:
        if _date_grounded_in_ocr(result.invoice_date, raw):
            kept.append("invoice_date")
        else:
            updates["invoice_date"] = None
            cleared.append("invoice_date")

    if result.total is not None:
        money_forms = _ocr_money_forms(raw)
        if money_forms and not _money_grounded_in_ocr(result.total, raw, field_key="total"):
            updates["total"] = None
            cleared.append("total")
        else:
            kept.append("total")

    # Currency: leave for reconcile_currency_from_text (ISO corroboration).
    if result.currency:
        kept.append("currency_deferred")

    if not cleared and not recovered and "invoice_no" not in updates:
        detail["cleared"] = []
        detail["kept"] = kept
        detail["recovered"] = []
        return result, detail

    grounded = replace(result, **updates) if updates else result
    drop = min(0.35, 0.08 * len(cleared))
    new_conf = max(0.0, round(result.confidence - drop, 4))
    reason = result.reason or ""
    if cleared:
        reason = (
            f"{reason}; cleared_ungrounded={','.join(cleared)}"
            if reason
            else f"cleared_ungrounded={','.join(cleared)}"
        )
    if recovered:
        reason = (
            f"{reason}; recovered_from_text={','.join(recovered)}"
            if reason
            else f"recovered_from_text={','.join(recovered)}"
        )
    grounded = replace(
        grounded,
        confidence=new_conf,
        needs_review=grounded.needs_review or len(cleared) >= 2 or new_conf < 0.55,
        reason=reason[:500],
    )
    detail["cleared"] = cleared
    detail["kept"] = kept
    detail["recovered"] = recovered
    detail["confidence_after"] = new_conf
    return grounded, detail


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
    # Clear totals that never appear in rich text (invented amounts).
    if (
        invoice.total is not None
        and text_usable_for_header_grounding(text)
    ):
        from app.services.extraction.field_grounding_service import (
            _money_grounded_in_ocr,
            _ocr_money_forms,
        )

        if _ocr_money_forms(text or "") and not _money_grounded_in_ocr(
            invoice.total, text, field_key="total"
        ):
            invoice.total = None
            fields = dict(invoice.extracted_fields or {})
            fields.pop("total", None)
            invoice.extracted_fields = fields
            detail["total_reason"] = "cleared_ungrounded_total"
    detail["total_after"] = str(invoice.total) if invoice.total is not None else None
    return detail
