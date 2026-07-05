"""OCR grounding and validation for extracted scalar fields."""

from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal

from app.services.invoice.invoice_data import InvoiceData
from app.utils.abn_validator import storage_abn
from app.utils.tax_id_validator import is_acceptable_tax_id

_PLACEHOLDER_PATTERNS = (
    re.compile(r"^45123456789$"),
    re.compile(r"^(\d)\1{5,}$"),
)

_PHONE_LINE = re.compile(r"\b(?:phone|tel(?:ephone)?|mobile|fax|\+1|support@)\b", re.I)

_BSB_FORMAT = re.compile(r"^\d{3}[-\s]?\d{3}$")
_ACCOUNT_FORMAT = re.compile(r"^\d{5,12}$")


def _normalize_alnum(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _is_placeholder(value: str) -> bool:
    token = re.sub(r"\s+", "", value)
    if not token:
        return False
    digits = "".join(c for c in token if c.isdigit())
    for pattern in _PLACEHOLDER_PATTERNS:
        if pattern.match(digits or token):
            return True
    return False


def _money_grounded_in_ocr(value: Decimal | str | None, ocr_text: str | None) -> bool:
    if value is None or not ocr_text:
        return value is None
    token = str(value).strip()
    if not token:
        return True
    compact = token.replace(",", "")
    ocr_compact = ocr_text.replace(",", "")
    if compact in ocr_compact:
        return True
    digits = "".join(c for c in token if c.isdigit())
    if digits and re.search(rf"(?<!\d){re.escape(digits)}(?!\d)", ocr_compact):
        return True
    return False


def value_grounded_in_ocr(value: str | None, ocr_text: str | None) -> bool:
    """True when value is empty or provably present in OCR text."""
    if not value or not str(value).strip():
        return True
    if not ocr_text:
        return False
    token = str(value).strip()
    if _is_placeholder(token):
        return False

    norm_val = _normalize_alnum(token)
    norm_ocr = _normalize_alnum(ocr_text)
    if norm_val and len(norm_val) >= 4 and norm_val in norm_ocr:
        return True

    if re.fullmatch(r"[\d\s.\-/,]+", token):
        digits = "".join(c for c in token if c.isdigit())
        if len(digits) >= 8:
            if re.search(rf"(?<!\d){re.escape(digits)}(?!\d)", ocr_text):
                return True
        return False

    escaped = re.escape(token)
    if re.search(rf"(?<!\w){escaped}(?!\w)", ocr_text, re.I):
        return True
    return False


def validate_bank_bsb(bsb: str | None, ocr_text: str | None = None) -> str | None:
    if not bsb or not str(bsb).strip():
        return None
    token = str(bsb).strip()
    if not _BSB_FORMAT.match(token):
        return None
    normalized = re.sub(r"\s+", "", token)
    if len(normalized.replace("-", "")) != 6:
        return None
    if ocr_text:
        line = _line_for_token(ocr_text, token)
        if line and _PHONE_LINE.search(line):
            return None
        if not value_grounded_in_ocr(token, ocr_text):
            return None
    return normalized if "-" in normalized else f"{normalized[:3]}-{normalized[3:]}"


def validate_bank_account(account: str | None, ocr_text: str | None = None) -> str | None:
    if not account or not str(account).strip():
        return None
    token = re.sub(r"\s+", "", str(account).strip())
    if not _ACCOUNT_FORMAT.match(token):
        return None
    if ocr_text:
        line = _line_for_token(ocr_text, token)
        if line and _PHONE_LINE.search(line):
            return None
        if not value_grounded_in_ocr(token, ocr_text):
            return None
    return token


def _line_for_token(text: str, token: str) -> str | None:
    digits = "".join(c for c in token if c.isdigit())
    for line in text.splitlines():
        if token in line or (digits and digits in line):
            return line
    return None


def merge_bank_fields(
    *,
    llm_bsb: str | None,
    llm_account: str | None,
    regex_bsb: str | None,
    regex_account: str | None,
    ocr_text: str | None,
) -> tuple[str | None, str | None]:
    """Prefer grounded LLM bank fields; fall back to validated regex."""
    bsb = validate_bank_bsb(llm_bsb, ocr_text)
    account = validate_bank_account(llm_account, ocr_text)
    if not bsb:
        bsb = validate_bank_bsb(regex_bsb, ocr_text)
    if not account:
        account = validate_bank_account(regex_account, ocr_text)
    return bsb, account


def ground_invoice_scalars(data: InvoiceData, ocr_text: str | None) -> InvoiceData:
    """Clear scalar fields that cannot be verified in OCR."""
    updates: dict[str, object] = {}

    for field in ("invoice_no", "po_reference"):
        current = getattr(data, field, None)
        if current and not value_grounded_in_ocr(str(current), ocr_text):
            updates[field] = None

    for field in ("subtotal", "gst", "total"):
        current = getattr(data, field, None)
        if current is not None:
            if not _money_grounded_in_ocr(current, ocr_text):
                updates[field] = None

    if data.due_date is not None:
        if not value_grounded_in_ocr(data.due_date.isoformat(), ocr_text):
            iso = data.due_date.strftime("%d/%m/%Y")
            if not value_grounded_in_ocr(iso, ocr_text):
                updates["due_date"] = None

    abn_raw = (data.abn or "").strip()
    if abn_raw:
        if not value_grounded_in_ocr(abn_raw, ocr_text):
            updates["abn"] = None
        else:
            stored = storage_abn(abn_raw)
            if not stored or not is_acceptable_tax_id(abn_raw):
                if not is_acceptable_tax_id(abn_raw):
                    updates["abn"] = None
                else:
                    updates["abn"] = stored
            else:
                updates["abn"] = stored

    bsb = validate_bank_bsb(data.bank_bsb, ocr_text)
    account = validate_bank_account(data.bank_account, ocr_text)
    if (data.bank_bsb or "").strip() != (bsb or ""):
        updates["bank_bsb"] = bsb
    if (data.bank_account or "").strip() != (account or ""):
        updates["bank_account"] = account

    if not updates:
        return data
    return replace(data, **updates)
