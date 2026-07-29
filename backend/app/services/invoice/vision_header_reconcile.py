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
    from app.services.shared.currency import currency_evidence_in_text

    return currency_evidence_in_text(iso, text)


def reconcile_currency_from_text(
    *,
    current_currency: str | None,
    text: str | None,
) -> tuple[str, str | None, str]:
    """Return (iso_or_empty, currency_symbol_or_none, reason).

    Unambiguous OCR evidence wins over a wrong vision ISO (e.g. bare ``$`` → USD).
    Ungrounded ISO codes are cleared when text is rich enough to judge.
    Thin/junk text must not wipe a vision ISO that the page images actually supported.
    """
    current = (current_currency or "").strip().upper()
    if current and not is_iso4217_currency(current):
        current = ""

    text_usable = text_usable_for_header_grounding(text)

    iso, symbol = resolve_currency_from_ocr(text, existing_currency=None)
    if iso:
        if current and current != iso:
            # Dual-currency docs: OCR "first code wins" must not flip a vision ISO
            # that also appears as a column header / tagged amount on the page.
            from app.services.shared.currency_total_pair import (
                detect_multi_currency_in_text,
                iso_appears_as_currency_column,
            )

            current_supported = _iso_corroborated_in_text(current, text) or (
                iso_appears_as_currency_column(current, text)
            )
            if detect_multi_currency_in_text(text) and current_supported:
                return current, None, "keep_vision_iso_multi_currency"
            return iso, None, f"ocr_override_{current}_to_{iso}"
        if not current:
            return iso, None, f"ocr_fill_{iso}"
        return current, None, "ocr_confirms_iso"

    if symbol and symbol in AMBIGUOUS_CURRENCY_SYMBOLS:
        if current and _iso_corroborated_in_text(current, text):
            return current, None, "keep_corroborated_vision_iso"
        # Bare $ / ¥ with no ISO corroboration — never keep a guessed code when
        # text is rich enough to have shown a code if one existed.
        if text_usable:
            return (
                "",
                symbol,
                "cleared_uncorroborated_iso" if current else f"ambiguous_symbol_{symbol}",
            )
        if current:
            return current, None, "keep_vision_iso_thin_text"
        return "", symbol, f"ambiguous_symbol_{symbol}"

    if symbol:
        return current, symbol, "symbol_only"

    if current and _iso_corroborated_in_text(current, text):
        return current, None, "keep_corroborated_vision_iso"
    if current:
        from app.services.shared.currency_total_pair import iso_appears_as_currency_column

        if iso_appears_as_currency_column(current, text):
            return current, None, "keep_vision_iso_column_header"
    if current and text_usable:
        # Vision invented an ISO with no text support — leave empty for human pick.
        return "", None, "cleared_ungrounded_iso"
    if current:
        return current, None, "keep_vision_iso_thin_text"
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


def resolve_header_grounding_text(path: Any) -> tuple[str, dict[str, Any]]:
    """Local PDF text, then hybrid Azure DI when scans/images yield empty/thin text.

    Understood-path vision skips full OCR, but header grounding still needs glyphs
    and labeled INV NO / Permit No tokens — especially for JPG uploads and
    image-only PDFs where pdfplumber returns nothing.
    """
    from pathlib import Path

    from app.services.extraction.pdf_page_text_service import (
        extract_local_pdf_plain_text,
        extract_pdf_page_texts,
    )

    detail: dict[str, Any] = {"source": "local", "local_chars": 0, "final_chars": 0}
    file_path = Path(path)
    local = extract_local_pdf_plain_text(file_path) or ""
    detail["local_chars"] = len(local.strip())
    if text_usable_for_header_grounding(local):
        detail["final_chars"] = detail["local_chars"]
        return local, detail

    try:
        extraction = extract_pdf_page_texts(file_path)
        hybrid = "\n".join(page.text or "" for page in extraction.pages)
    except Exception as exc:
        detail["source"] = "local_thin"
        detail["hybrid_error"] = str(exc)[:200]
        detail["final_chars"] = detail["local_chars"]
        return local, detail

    hybrid_chars = len((hybrid or "").strip())
    detail["hybrid_chars"] = hybrid_chars
    detail["incomplete_ocr_indices"] = list(extraction.incomplete_ocr_indices or ())
    if text_usable_for_header_grounding(hybrid):
        detail["source"] = "hybrid_di"
        detail["final_chars"] = hybrid_chars
        return hybrid, detail

    # Prefer whichever is longer when both are thin.
    if hybrid_chars > detail["local_chars"]:
        detail["source"] = "hybrid_di_thin"
        detail["final_chars"] = hybrid_chars
        return hybrid or "", detail
    detail["source"] = "local_thin"
    detail["final_chars"] = detail["local_chars"]
    return local, detail


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
    """Commercial Invoice/INV labels only — never Permit/Doc/AWB."""
    from app.services.extraction.invoice_no_sanitizer import (
        extract_commercial_invoice_no_from_text,
    )

    return (extract_commercial_invoice_no_from_text(text or "") or "").strip()


def _recover_invoice_date_from_text(text: str | None, *, date_order: str = "DMY"):
    """Recover issuance date from labeled PDF text; skip due/validity labels."""
    from app.services.shared.flexible_date import recover_labeled_invoice_date_from_text

    order = date_order if date_order in {"DMY", "MDY", "YMD"} else "DMY"
    return recover_labeled_invoice_date_from_text(text, date_order=order)  # type: ignore[arg-type]


_PERMIT_NO_LINE = re.compile(
    r"(?im)(?:Permit\s*(?:No\.?|Number|#))\s*[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})"
)
_UNIQUE_REF_LINE = re.compile(
    r"(?im)(?:Unique\s*Ref(?:erence)?)\s*[:\s#]*([A-Z0-9][A-Z0-9\-/\s]{4,80})"
)
_NON_INVOICE_ID_LINE = re.compile(
    r"(?im)(?:"
    r"Permit\s*(?:No\.?|Number|#)|"
    r"Clearance\s*(?:No\.?|Number|#)|"
    r"Declaration\s*(?:No\.?|Number|#)|"
    r"Document\s*(?:No\.?|Number|#)|"
    r"Doc\.?\s*(?:No\.?|#)|"
    r"Unique\s*Ref(?:erence)?|"
    r"(?:Master\s+)?AWB\s*(?:No\.?|Number|#)?|"
    r"HAWB\s*(?:No\.?|Number|#)?|"
    r"(?:Bill\s+of\s+Lading|B/?L|BOL)\s*(?:No\.?|Number|#)?"
    r")\s*[:\s#]*([A-Z0-9][A-Z0-9\-/\s]{2,80})"
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


def _norm_id_token(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _is_non_invoice_labeled_id(value: str | None, text: str | None) -> bool:
    """True when value matches a Permit/Doc/Unique Ref/AWB/BL labeled token."""
    needle = _norm_id_token(value)
    if len(needle) < 4:
        return False
    for match in _NON_INVOICE_ID_LINE.finditer(text or ""):
        candidate = _norm_id_token(match.group(1))
        if not candidate:
            continue
        if needle == candidate or needle in candidate or candidate in needle:
            return True
    return False


def enrich_vision_header_refs_from_text(
    result: Any,
    text: str | None,
    *,
    date_order: str = "DMY",
) -> tuple[Any, dict[str, Any]]:
    """Fill invoice_no / other_reference from labeled PDF text when missing.

    ``invoice_no`` only from Invoice/INV labels. Permit No goes to other_reference
    (including when no commercial invoice number exists).
    """
    from app.services.extraction.invoice_no_sanitizer import sanitize_invoice_no
    from app.services.invoice.vision_header_extract import VisionHeaderExtractResult

    detail: dict[str, Any] = {"filled": []}
    if not isinstance(result, VisionHeaderExtractResult) or not result.success:
        return result, detail
    if not text_usable_for_header_grounding(text):
        return result, detail

    updates: dict[str, Any] = {}
    inv_raw = (result.invoice_no or "").strip()
    inv = (sanitize_invoice_no(inv_raw) or "").strip()
    if inv_raw and not inv:
        updates["invoice_no"] = ""
        detail["filled"].append("invoice_no_cleared_label_word")
    recovered_inv = _recover_invoice_no_from_text(text)
    permit = _recover_permit_no_from_text(text)

    # Drop permit/doc/AWB etc. that vision incorrectly put in invoice_no.
    if inv and not recovered_inv and _is_non_invoice_labeled_id(inv, text):
        updates["invoice_no"] = ""
        inv = ""
        detail["filled"].append("invoice_no_cleared_non_invoice_id")

    if not inv and recovered_inv:
        updates["invoice_no"] = recovered_inv
        inv = recovered_inv
        detail["filled"].append("invoice_no")

    other = _normalize_other_reference(result.other_reference)
    unique_match = _UNIQUE_REF_LINE.search(text or "")
    unique_ref = _normalize_other_reference(unique_match.group(1) if unique_match else "")

    prefer_permit_as_other = bool(
        permit
        and (
            not other
            or _looks_like_unique_ref_blob(other)
            or (unique_ref and other.upper() == unique_ref.upper())
            or (inv and other.upper() == inv.upper())
        )
        and (not inv or permit.upper() != inv.upper())
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

    if result.invoice_date is None:
        recovered_date = _recover_invoice_date_from_text(text, date_order=date_order)
        if recovered_date is not None:
            updates["invoice_date"] = recovered_date
            detail["filled"].append("invoice_date")

    if not updates:
        return result, detail
    return replace(result, **updates), detail


def ground_vision_header_result(
    result: Any,
    text: str | None,
    *,
    date_order: str = "DMY",
) -> tuple[Any, dict[str, Any]]:
    """Clear header fields that cannot be verified in local PDF text.

    Skips grounding when text is thin (scans) so vision remains the source of
    truth. ``canonical_document_type`` and ``perspective`` are not grounded —
    they are normalized / inferred labels, not literal page tokens.

    ``invoice_no`` is recovered only from labeled Invoice/INV text when vision
    left it empty or grounding would clear a value that OCR text supports under
    a softer match. Permit/Doc/AWB numbers are never recovered into invoice_no.
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

    from app.services.extraction.invoice_no_sanitizer import (
        extract_commercial_invoice_no_from_text,
        is_plausible_invoice_no,
        sanitize_invoice_no,
    )

    vision_raw = (result.invoice_no or "").strip()
    vision_inv = (sanitize_invoice_no(vision_raw) or "").strip()
    if vision_raw and not vision_inv:
        # Column-header bleed (e.g. "Customer" from "Customer PO") — treat as missing.
        detail["invoice_no_vision_rejected"] = vision_raw

    commercial_inv = ""
    try:
        commercial_inv = (extract_commercial_invoice_no_from_text(raw) or "").strip()
    except Exception:
        commercial_inv = ""
    if commercial_inv and not is_plausible_invoice_no(commercial_inv):
        commercial_inv = ""

    if vision_inv and _invoice_no_soft_grounded(vision_inv, raw):
        # Prefer labeled commercial INV NO over a soft-grounded permit/booking/doc id
        # (or OCR near-miss of the same invoice token).
        if commercial_inv and commercial_inv.upper() != vision_inv.upper():
            updates["invoice_no"] = commercial_inv
            recovered.append("invoice_no")
            detail["invoice_no_vision_cleared"] = vision_inv
            detail["invoice_no_prefer_commercial"] = commercial_inv
        elif not commercial_inv and _is_non_invoice_labeled_id(vision_inv, raw):
            # Soft-grounded but it's a Permit/Doc/AWB/Unique Ref — not invoice_no.
            updates["invoice_no"] = ""
            cleared.append("invoice_no")
            detail["invoice_no_vision_cleared"] = vision_inv
            detail["invoice_no_cleared_reason"] = "non_invoice_labeled_id"
        else:
            if vision_inv != vision_raw:
                updates["invoice_no"] = vision_inv
            kept.append("invoice_no")
    elif vision_inv:
        # Vision value not corroborated — try labeled Invoice/INV recovery before clearing.
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
        elif vision_raw:
            # Rejected label word with no recovery — clear so it does not persist.
            updates["invoice_no"] = ""
            cleared.append("invoice_no")
            detail["invoice_no_vision_cleared"] = vision_raw
            detail["invoice_no_cleared_reason"] = "label_word_rejected"
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
            recovered_date = _recover_invoice_date_from_text(raw, date_order=date_order)
            if recovered_date is not None and _date_grounded_in_ocr(recovered_date, raw):
                updates["invoice_date"] = recovered_date
                recovered.append("invoice_date")
                detail["invoice_date_vision_cleared"] = result.invoice_date.isoformat()
            else:
                updates["invoice_date"] = None
                cleared.append("invoice_date")
    else:
        recovered_date = _recover_invoice_date_from_text(raw, date_order=date_order)
        if recovered_date is not None:
            updates["invoice_date"] = recovered_date
            recovered.append("invoice_date")

    if result.total is not None:
        money_forms = _ocr_money_forms(raw)
        if money_forms and not _money_grounded_in_ocr(result.total, raw, field_key="total"):
            updates["total"] = None
            cleared.append("total")
        else:
            kept.append("total")

    if result.subtotal is not None:
        money_forms = _ocr_money_forms(raw)
        if money_forms and not _money_grounded_in_ocr(
            result.subtotal, raw, field_key="subtotal"
        ):
            updates["subtotal"] = None
            cleared.append("subtotal")
        else:
            kept.append("subtotal")

    if result.gst is not None:
        money_forms = _ocr_money_forms(raw)
        if money_forms and not _money_grounded_in_ocr(result.gst, raw, field_key="gst"):
            updates["gst"] = None
            cleared.append("gst")
        else:
            kept.append("gst")

    for tax_field in ("seller_abn", "buyer_abn"):
        tax_val = (getattr(result, tax_field) or "").strip()
        if not tax_val:
            continue
        # Require digit/alnum token to appear in OCR text when text is rich.
        digits = re.sub(r"\D", "", tax_val)
        token = re.sub(r"\s+", "", tax_val).upper()
        hay = re.sub(r"\s+", "", raw).upper()
        grounded = False
        if digits and len(digits) >= 8 and digits in re.sub(r"\D", "", raw):
            grounded = True
        elif token and len(token) >= 6 and token in hay:
            grounded = True
        if grounded:
            kept.append(tax_field)
        else:
            updates[tax_field] = ""
            cleared.append(tax_field)

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

    # Multi-currency dual-column / FX layouts: bind total to selected currency.
    from app.services.shared.currency_total_pair import reconcile_currency_total_pair

    pair = reconcile_currency_total_pair(
        currency=invoice.currency,
        total=invoice.total,
        text=text,
    )
    detail["pair_reason"] = pair.reason
    detail["multi_currency"] = pair.multi_currency
    if pair.currency != (invoice.currency or "").strip().upper():
        invoice.currency = pair.currency
        fields = dict(invoice.extracted_fields or {})
        if pair.currency:
            fields["currency"] = pair.currency
            fields.pop("currency_symbol", None)
        else:
            fields.pop("currency", None)
        invoice.extracted_fields = fields
        detail["currency_after"] = pair.currency or None
        detail["currency_reason"] = f"{detail['currency_reason']};{pair.reason}"
    if pair.total != invoice.total:
        invoice.total = pair.total
        fields = dict(invoice.extracted_fields or {})
        if pair.total is not None:
            fields["total"] = format(pair.total, "f")
        else:
            fields.pop("total", None)
        invoice.extracted_fields = fields
        detail["total_reason"] = (
            f"{detail['total_reason']};{pair.reason}"
            if detail.get("total_reason")
            else pair.reason
        )

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


_AMOUNT_CONSISTENCY_EPS = Decimal("0.05")
_LINE_SUM_MISMATCH_RATIO = Decimal("0.15")


def _amount_near(a: Decimal | None, b: Decimal | None) -> bool:
    if a is None or b is None:
        return False
    return (a - b).copy_abs() <= _AMOUNT_CONSISTENCY_EPS


def apply_vision_header_amount_consistency(result: Any) -> tuple[Any, dict[str, Any]]:
    """Flag / clear inconsistent amounts without inventing balancing figures.

    If subtotal + gst differs from total beyond epsilon, clear the weaker field.
    When line items sum to total (not subtotal), clear the mismatched subtotal
    (common dual-currency / wrong-box case) and treat the header as resolved.
    When subtotal ≈ total and gst > 0, subtotal is treated as tax-inclusive (or a
    line dump that already includes CGST/SGST) — clear subtotal so journal can
    use total − gst. Otherwise prefer clearing gst. Never write a computed
    balancing amount into the cleared field.
    """
    from app.services.invoice.invoice_amounts import amounts_look_tax_inclusive_subtotal

    detail: dict[str, Any] = {"cleared": [], "flags": []}
    subtotal = result.subtotal
    gst = result.gst
    total = result.total
    updates: dict[str, Any] = {}

    lines = list(result.line_items or ())
    line_sum: Decimal | None = None
    if lines:
        line_amounts = [li.amount for li in lines if li.amount is not None]
        if line_amounts:
            line_sum = sum(line_amounts, start=Decimal("0"))
            detail["line_sum"] = str(line_sum)

    def _header_amounts_disagree(
        st: Decimal | None,
        tax: Decimal | None,
        tot: Decimal | None,
    ) -> bool:
        if st is None or tot is None:
            return False
        if tax is not None:
            return (st + tax - tot).copy_abs() > _AMOUNT_CONSISTENCY_EPS
        return (st - tot).copy_abs() > _AMOUNT_CONSISTENCY_EPS

    if _header_amounts_disagree(subtotal, gst, total):
        detail["flags"].append("subtotal_gst_total_mismatch")
        if gst is not None and total is not None and subtotal is not None:
            detail["delta"] = str((subtotal + gst - total).copy_abs())
        elif subtotal is not None and total is not None:
            detail["delta"] = str((subtotal - total).copy_abs())

        line_picks_total = (
            line_sum is not None
            and line_sum > 0
            and _amount_near(line_sum, total)
            and not _amount_near(line_sum, subtotal)
        )
        if line_picks_total:
            # Settlement total agrees with lines; drop foreign/wrong-box subtotal.
            updates["subtotal"] = None
            detail["cleared"].append("subtotal")
            detail["flags"].append("line_sum_selected_total")
        elif subtotal is not None and gst is not None and total is not None:
            if amounts_look_tax_inclusive_subtotal(
                subtotal=subtotal, gst=gst, total=total
            ):
                # Expense base was set to gross — drop it; keep gst + total.
                updates["subtotal"] = None
                detail["cleared"].append("subtotal")
                detail["flags"].append("tax_inclusive_subtotal")
            else:
                # Prefer clearing gst (often confused with rate or partial tax).
                updates["gst"] = None
                detail["cleared"].append("gst")
            updates["amount_inconsistency"] = True
            updates["needs_review"] = True
        else:
            updates["amount_inconsistency"] = True
            updates["needs_review"] = True

    remaining_subtotal = updates["subtotal"] if "subtotal" in updates else subtotal
    remaining_total = updates["total"] if "total" in updates else total
    if line_sum is not None and line_sum > 0 and (
        remaining_total is not None or remaining_subtotal is not None
    ):
        anchor = remaining_subtotal if remaining_subtotal is not None else remaining_total
        if anchor is not None and anchor > 0:
            if _amount_near(line_sum, anchor):
                detail["anchor"] = str(anchor)
            else:
                ratio = (line_sum - anchor).copy_abs() / anchor
                if ratio > _LINE_SUM_MISMATCH_RATIO:
                    detail["flags"].append("line_items_amount_mismatch")
                    detail["anchor"] = str(anchor)
                    updates["line_items_amount_mismatch"] = True
                    updates["needs_review"] = True

    if not updates:
        return result, detail
    return replace(result, **updates), detail
