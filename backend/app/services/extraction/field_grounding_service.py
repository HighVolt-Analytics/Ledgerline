"""OCR grounding and validation for extracted scalar fields."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.services.extraction.extraction_field_values import (
    expand_extraction_keys_for_llm,
    extracted_fields_from_parsed,
    non_canonical_extraction_keys,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.shared.flexible_date import _NAME_FORMATS, _NUMERIC_FORMATS_DMY, _NUMERIC_FORMATS_MDY
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


def _date_grounded_in_ocr(value: date | None, ocr_text: str | None) -> bool:
    if value is None:
        return True
    if not ocr_text:
        return False
    formats = _NUMERIC_FORMATS_DMY + _NUMERIC_FORMATS_MDY + _NAME_FORMATS
    for fmt in formats:
        try:
            token = value.strftime(fmt)
        except ValueError:
            continue
        if value_grounded_in_ocr(token, ocr_text):
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


def ground_extracted_fields_map(
    fields: dict[str, str] | None,
    ocr_text: str | None,
    *,
    requested_keys: Sequence[str] | None = None,
) -> dict[str, str]:
    """Clear string field values that cannot be verified in OCR."""
    if not fields:
        return {}
    allowed = {str(k).strip().lower() for k in (requested_keys or fields.keys())}
    grounded: dict[str, str] = {}
    for key, value in fields.items():
        token = str(key or "").strip().lower()
        if requested_keys is not None and token not in allowed:
            continue
        text = str(value or "").strip()
        if text and value_grounded_in_ocr(text, ocr_text):
            grounded[token] = text
    return grounded


def ground_invoice_scalars(data: InvoiceData, ocr_text: str | None) -> InvoiceData:
    """Clear scalar fields that cannot be verified in OCR."""
    updates: dict[str, object] = {}

    for field in ("invoice_no", "po_reference", "cost_centre", "vendor", "billing_address", "document_heading"):
        current = getattr(data, field, None)
        if current and not value_grounded_in_ocr(str(current), ocr_text):
            updates[field] = None

    if data.invoice_date is not None and not _date_grounded_in_ocr(data.invoice_date, ocr_text):
        updates["invoice_date"] = None

    for field in ("subtotal", "gst", "total"):
        current = getattr(data, field, None)
        if current is not None:
            if not _money_grounded_in_ocr(current, ocr_text):
                updates[field] = None

    if data.due_date is not None and not _date_grounded_in_ocr(data.due_date, ocr_text):
        updates["due_date"] = None

    currency = (data.currency or "").strip()
    if currency and not value_grounded_in_ocr(currency, ocr_text):
        updates["currency"] = ""

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

    extracted = ground_extracted_fields_map(
        extracted_fields_from_parsed(data),
        ocr_text,
    )
    if extracted != extracted_fields_from_parsed(data):
        updates["extracted_fields"] = extracted

    if not updates:
        return data
    return replace(data, **updates)


def ground_parsed_fields(
    parsed: InvoiceData,
    ocr_text: str | None,
    selected_keys: Sequence[str],
    ocr_payload: dict[str, object] | None = None,
) -> InvoiceData:
    """Filter and ground parsed extraction output before OCR backfill."""
    from app.services.extraction.extraction_field_values import (
        clear_llm_scalars_for_di_populated_fields,
        filter_parsed_to_requested_keys,
        prebuilt_invoice_scalars_active,
    )
    from app.services.extraction.line_items_parser import (
        document_has_charge_lines,
        document_has_product_table,
        resolve_line_items_from_ocr_payload,
    )

    filtered = filter_parsed_to_requested_keys(parsed, selected_keys)
    grounded = ground_invoice_scalars(filtered, ocr_text)
    if prebuilt_invoice_scalars_active(ocr_payload):
        grounded = clear_llm_scalars_for_di_populated_fields(grounded, selected_keys, ocr_payload)
    selected = {str(key or "").strip().lower() for key in selected_keys if str(key or "").strip()}
    if "line_items" in selected:
        payload = ocr_payload or {}
        if resolve_line_items_from_ocr_payload(payload):
            grounded = replace(grounded, line_items=[])
        elif not document_has_product_table(ocr_text, payload) and not document_has_charge_lines(
            ocr_text
        ):
            grounded = replace(grounded, line_items=[])
    custom_keys = non_canonical_extraction_keys(selected_keys)
    if custom_keys:
        extracted = ground_extracted_fields_map(
            extracted_fields_from_parsed(grounded),
            ocr_text,
            requested_keys=list(expand_extraction_keys_for_llm(selected_keys)) + custom_keys,
        )
        if extracted != extracted_fields_from_parsed(grounded):
            grounded = replace(grounded, extracted_fields=extracted)
    return grounded
