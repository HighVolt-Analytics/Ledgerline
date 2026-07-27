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


def _grounding_required_for_field(field_key: str) -> bool:
    from app.registry.adapter import get_registry_adapter

    return get_registry_adapter().grounding_required(field_key)


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


def _normalize_money_for_grounding(value: Decimal | str) -> str:
    from app.services.shared.locale_number_parser import parse_localized_decimal

    if isinstance(value, Decimal):
        token = str(value).strip()
        try:
            return format(value.normalize(), "f").rstrip("0").rstrip(".")
        except Exception:
            pass
    else:
        token = str(value).strip()
    parsed = parse_localized_decimal(token)
    if parsed is not None:
        try:
            return format(parsed.normalize(), "f").rstrip("0").rstrip(".")
        except Exception:
            return str(parsed)
    cleaned = re.sub(r"[^\d.\-]", "", token.replace(",", ""))
    if not cleaned:
        return ""
    try:
        return format(Decimal(cleaned).normalize(), "f").rstrip("0").rstrip(".")
    except Exception:
        return cleaned


def _ocr_money_forms(ocr_text: str) -> set[str]:
    forms: set[str] = set()
    compact = re.sub(r"[^\d.\-]", "", ocr_text.replace(",", ""))
    for match in re.finditer(r"-?\d+\.?\d*", compact):
        normalized = _normalize_money_for_grounding(match.group(0))
        if normalized:
            forms.add(normalized)
    return forms


def _money_grounded_adjacent_line(
    value: Decimal | str,
    ocr_text: str | None,
    *,
    field_key: str | None = None,
) -> bool:
    if not ocr_text or value is None:
        return False
    target = _normalize_money_for_grounding(value)
    if not target:
        return False
    lines = ocr_text.splitlines()
    from app.services.extraction.finance_field_labels import label_matches_field

    keys = [field_key] if field_key else ("subtotal", "gst", "total")
    for index, line in enumerate(lines):
        for key in keys:
            if not key or not label_matches_field(line, key):
                continue
            for offset in (0, 1, 2):
                next_index = index + offset
                if next_index >= len(lines):
                    break
                candidate = _normalize_money_for_grounding(lines[next_index])
                if candidate == target:
                    return True
    return False


# Indian GST split tax: vision often stores CGST+SGST as one gst total that never
# appears as a single token on the page (only the components do).
_COMPONENT_TAX_KIND = re.compile(
    r"(?is)\b(?P<kind>c\s*gst|s\s*gst|i\s*gst)\b"
)
_COMPONENT_TAX_RATE = re.compile(r"@\s*\d+(?:\.\d+)?\s*%|\b\d+(?:\.\d+)?\s*%")
_COMPONENT_TAX_MONEY = re.compile(
    r"(?:₹|rs\.?\s*|inr\s*)?(?P<amt>[\d][\d,]*(?:\.\d{1,4})?)",
    re.I,
)
_GST_COMPONENT_EPS = Decimal("0.02")


def _first_money_skipping_tax_rates(text: str) -> Decimal | None:
    """Parse the first money token after stripping % rates (e.g. ``CGST @9%``)."""
    from app.services.extraction.field_validators import normalize_amount

    cleaned = _COMPONENT_TAX_RATE.sub(" ", text or "")
    for match in _COMPONENT_TAX_MONEY.finditer(cleaned):
        money = normalize_amount(match.group("amt"))
        if money is not None and money > 0:
            return money
    return None


def _gst_component_amounts_from_ocr(ocr_text: str) -> dict[str, Decimal]:
    """Map ``cgst`` / ``sgst`` / ``igst`` → amount from labeled OCR lines."""
    found: dict[str, Decimal] = {}
    lines = (ocr_text or "").splitlines()
    for index, line in enumerate(lines):
        match = _COMPONENT_TAX_KIND.search(line)
        if not match:
            continue
        kind = re.sub(r"\s+", "", match.group("kind").lower())
        if kind in found:
            continue
        amount = _first_money_skipping_tax_rates(line[match.end() :])
        if amount is None:
            for offset in (1, 2):
                next_index = index + offset
                if next_index >= len(lines):
                    break
                amount = _first_money_skipping_tax_rates(lines[next_index])
                if amount is not None:
                    break
        if amount is not None:
            found[kind] = amount
    return found


def _gst_grounded_via_component_sum(
    value: Decimal | str,
    ocr_text: str,
) -> bool:
    """True when gst equals IGST or CGST+SGST component amounts on the page."""
    target = _normalize_money_for_grounding(value)
    if not target:
        return False
    try:
        target_dec = Decimal(target)
    except Exception:
        return False
    comps = _gst_component_amounts_from_ocr(ocr_text)
    if not comps:
        return False
    igst = comps.get("igst")
    if igst is not None and (igst - target_dec).copy_abs() <= _GST_COMPONENT_EPS:
        return True
    cgst = comps.get("cgst")
    sgst = comps.get("sgst")
    if cgst is not None and sgst is not None:
        if (cgst + sgst - target_dec).copy_abs() <= _GST_COMPONENT_EPS:
            return True
    return False


def _money_grounded_in_ocr(
    value: Decimal | str | None,
    ocr_text: str | None,
    *,
    field_key: str | None = None,
) -> bool:
    if value is None or not ocr_text:
        return value is None
    token = str(value).strip()
    if not token:
        return True
    normalized = _normalize_money_for_grounding(value)
    if normalized and normalized in _ocr_money_forms(ocr_text):
        return True
    compact = token.replace(",", "")
    ocr_compact = ocr_text.replace(",", "")
    if compact in ocr_compact:
        return True
    digits = "".join(c for c in token if c.isdigit())
    if digits and re.search(rf"(?<!\d){re.escape(digits)}(?!\d)", ocr_compact):
        return True
    if (field_key or "").strip().lower() == "gst" and _gst_grounded_via_component_sum(
        value, ocr_text
    ):
        return True
    return _money_grounded_adjacent_line(value, ocr_text, field_key=field_key)


def _label_terms_for_field_key(field_key: str) -> list[str]:
    from app.services.extraction.extraction_field_values import _FIELD_HINT_PATTERNS
    from app.services.extraction.finance_field_labels import finance_label_terms

    token = str(field_key or "").strip().lower()
    if token in ("subtotal", "gst", "total", "gst_rate"):
        return finance_label_terms(token)
    hints = _FIELD_HINT_PATTERNS.get(token, "")
    if hints:
        return [part.strip() for part in hints.split(",") if part.strip()]
    return []


def _label_proximate_grounded(value: str, ocr_text: str, field_key: str) -> bool:
    terms = _label_terms_for_field_key(field_key)
    if not terms or not value.strip():
        return False
    lines = ocr_text.splitlines()
    value_token = value.strip()
    norm_val = _normalize_alnum(value_token)
    for index, line in enumerate(lines):
        line_lower = line.lower()
        if not any(term.lower() in line_lower for term in terms):
            continue
        for offset in range(3):
            probe_index = index + offset
            if probe_index >= len(lines):
                break
            probe = lines[probe_index]
            if value_token in probe or value_token.lower() in probe.lower():
                return True
            if norm_val and len(norm_val) >= 4 and norm_val in _normalize_alnum(probe):
                return True
    return False


def _substring_grounded_in_ocr(
    value: str,
    ocr_text: str,
    *,
    field_key: str | None = None,
) -> bool:
    token = str(value).strip()
    if _is_placeholder(token):
        return False

    norm_val = _normalize_alnum(token)
    norm_ocr = _normalize_alnum(ocr_text)
    if norm_val and len(norm_val) >= 4 and norm_val in norm_ocr:
        return True

    if re.fullmatch(r"[\d\s.\-/,]+", token):
        digits = "".join(c for c in token if c.isdigit())
        # Invoice / PO refs are often 4–7 digits; money/other digit runs stay stricter
        ref_keys = {
            "invoice_no",
            "po_reference",
            "so_reference",
            "grn_reference",
            "abn",
        }
        min_digits = 4 if (field_key or "") in ref_keys else 8
        if len(digits) >= min_digits:
            if re.search(rf"(?<!\d){re.escape(digits)}(?!\d)", ocr_text):
                return True
        return False

    escaped = re.escape(token)
    if re.search(rf"(?<!\w){escaped}(?!\w)", ocr_text, re.I):
        return True

    from app.services.master_data.vendor_name_utils import normalize_vendor_name

    normalized = normalize_vendor_name(token)
    if normalized and normalized != token:
        norm_vendor = _normalize_alnum(normalized)
        if norm_vendor and len(norm_vendor) >= 4 and norm_vendor in norm_ocr:
            return True
        escaped_norm = re.escape(normalized)
        if re.search(rf"(?<!\w){escaped_norm}(?!\w)", ocr_text, re.I):
            return True

    return False


def value_grounded_in_ocr(
    value: str | None,
    ocr_text: str | None,
    *,
    field_key: str | None = None,
    grounding_debug: dict[str, str] | None = None,
) -> bool:
    """True when value is empty or provably present in OCR text."""
    if not value or not str(value).strip():
        return True
    if not ocr_text:
        return False
    token = str(value).strip()
    key = str(field_key or "").strip().lower() or None

    if key:
        if key in ("subtotal", "gst", "total", "gst_rate"):
            try:
                amount = value if isinstance(value, Decimal) else Decimal(str(value).replace(",", ""))
                if _money_grounded_adjacent_line(amount, ocr_text, field_key=key):
                    if grounding_debug is not None:
                        grounding_debug[key] = "label_proximate"
                    return True
            except Exception:
                pass
        elif _label_proximate_grounded(token, ocr_text, key):
            if grounding_debug is not None:
                grounding_debug[key] = "label_proximate"
            return True

    if _substring_grounded_in_ocr(token, ocr_text, field_key=key):
        if grounding_debug is not None and key:
            grounding_debug[key] = "substring_fallback"
        return True
    return False


def _date_grounded_in_ocr(value: date | None, ocr_text: str | None) -> bool:
    if value is None:
        return True
    if not ocr_text:
        return False
    from app.services.shared.flexible_date import date_ocr_match_tokens

    for token in date_ocr_match_tokens(value):
        if value_grounded_in_ocr(token, ocr_text):
            return True
    return False


def _invoice_no_grounded(value: str | None, ocr_text: str | None) -> bool:
    """Invoice numbers must sanitize cleanly and the clean token must appear in OCR."""
    from app.services.extraction.invoice_no_sanitizer import (
        invoice_no_has_label_bleed,
        sanitize_invoice_no,
    )

    if not value or not str(value).strip():
        return True
    if invoice_no_has_label_bleed(value):
        clean = sanitize_invoice_no(value)
        if not clean:
            return False
        return value_grounded_in_ocr(clean, ocr_text, field_key="invoice_no") or value_grounded_in_ocr(
            str(value).strip(), ocr_text, field_key="invoice_no"
        )
    clean = sanitize_invoice_no(value)
    token = clean or str(value).strip()
    if not token:
        return False
    return value_grounded_in_ocr(token, ocr_text, field_key="invoice_no")


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
    grounding_debug: dict[str, str] | None = None,
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
        if text and not _grounding_required_for_field(token):
            grounded[token] = text
            continue
        if text and value_grounded_in_ocr(
            text,
            ocr_text,
            field_key=token,
            grounding_debug=grounding_debug,
        ):
            grounded[token] = text
    return grounded


def currency_implied_by_grounded_tax_id(
    data: InvoiceData,
    ocr_text: str | None,
) -> str | None:
    """Deprecated: tax IDs must not invent currency. Always returns None.

    Kept as a no-op stub so older imports/call sites do not invent ISO codes
    from ABN/GSTIN/etc. Currency must be literally evidenced on the document.
    """
    del data, ocr_text
    return None


def currency_passes_grounding(
    data: InvoiceData,
    ocr_text: str | None,
    *,
    org_country: str | None = None,
    grounding_debug: dict[str, str] | None = None,
) -> bool:
    """
    True when currency may be kept.

    Empty always passes. Otherwise require literal document evidence for the
    ISO code (explicit code, prefixed symbol like US$/S$, or unambiguous glyph
    like €/₹). Never keep a currency inferred from tax IDs, country, or tenant.
    """
    del org_country  # never used for currency invention
    currency = (data.currency or "").strip().upper()
    if not currency:
        return True

    from app.services.shared.currency import currency_evidence_in_text
    from app.services.shared.currency_total_pair import iso_appears_as_currency_column

    if currency_evidence_in_text(currency, ocr_text):
        if grounding_debug is not None:
            grounding_debug["currency"] = "literal_ocr"
        return True
    # Dual-column summaries (SGD | USD) corroborate both ISOs without inline amounts.
    if iso_appears_as_currency_column(currency, ocr_text):
        if grounding_debug is not None:
            grounding_debug["currency"] = "column_header"
        return True
    return False


def ground_invoice_scalars(
    data: InvoiceData,
    ocr_text: str | None,
    *,
    skip_keys: frozenset[str] | None = None,
    org_country: str | None = None,
) -> InvoiceData:
    """Clear scalar fields that cannot be verified in OCR."""
    skip = skip_keys or frozenset()
    updates: dict[str, object] = {}
    grounding_debug: dict[str, str] = {}

    from app.services.extraction.invoice_no_sanitizer import (
        apply_invoice_no_secondary,
        split_invoice_no_parts_and_date,
    )

    invoice_no = data.invoice_no
    if "invoice_no" not in skip and invoice_no:
        clean_no, secondary, bleed_date = split_invoice_no_parts_and_date(str(invoice_no))
        if clean_no != invoice_no:
            updates["invoice_no"] = clean_no
            invoice_no = clean_no
        current_extracted = dict(data.extracted_fields or {})
        if (
            bleed_date is not None
            and data.invoice_date is None
            and "invoice_date" not in skip
        ):
            updates["invoice_date"] = bleed_date
        if invoice_no and not _invoice_no_grounded(str(invoice_no), ocr_text):
            updates["invoice_no"] = None
            updates["extracted_fields"] = apply_invoice_no_secondary(current_extracted, None)
        else:
            if secondary and not _invoice_no_grounded(str(secondary), ocr_text):
                secondary = None
            updated_extracted = apply_invoice_no_secondary(current_extracted, secondary)
            if updated_extracted != current_extracted:
                updates["extracted_fields"] = updated_extracted

    for field in ("po_reference", "cost_centre", "vendor", "billing_address", "document_heading"):
        if field in skip:
            continue
        current = getattr(data, field, None)
        if current and not value_grounded_in_ocr(
            str(current),
            ocr_text,
            field_key=field,
            grounding_debug=grounding_debug,
        ):
            updates[field] = None

    resolved_date = updates.get("invoice_date", data.invoice_date)
    if (
        "invoice_date" not in skip
        and isinstance(resolved_date, date)
        and not _date_grounded_in_ocr(resolved_date, ocr_text)
    ):
        updates["invoice_date"] = None

    for field in ("subtotal", "gst", "total"):
        if field in skip:
            continue
        current = getattr(data, field, None)
        if current is not None:
            if not _money_grounded_in_ocr(current, ocr_text, field_key=field):
                updates[field] = None

    if "due_date" not in skip and data.due_date is not None and not _date_grounded_in_ocr(
        data.due_date, ocr_text
    ):
        updates["due_date"] = None

    # Ground ABN before currency so cleared tax IDs do not linger on the working copy.
    abn_raw = (data.abn or "").strip()
    working = data
    if abn_raw and "abn" not in skip:
        if not value_grounded_in_ocr(
            abn_raw,
            ocr_text,
            field_key="abn",
            grounding_debug=grounding_debug,
        ):
            updates["abn"] = None
            working = replace(data, abn=None)
        else:
            stored = storage_abn(abn_raw)
            if not stored or not is_acceptable_tax_id(abn_raw):
                if not is_acceptable_tax_id(abn_raw):
                    updates["abn"] = None
                    working = replace(data, abn=None)
                else:
                    updates["abn"] = stored
                    working = replace(data, abn=stored)
            else:
                updates["abn"] = stored
                working = replace(data, abn=stored)

    currency = (working.currency or "").strip()
    if "currency" not in skip and currency and not currency_passes_grounding(
        working,
        ocr_text,
        org_country=org_country,
        grounding_debug=grounding_debug,
    ):
        updates["currency"] = ""

    # Multi-currency dual-column: bind total to the grounded currency (and vice versa).
    if "total" not in skip or "currency" not in skip:
        from app.services.shared.currency_total_pair import reconcile_currency_total_pair

        resolved_currency = (
            updates["currency"] if "currency" in updates else working.currency
        )
        resolved_total = updates["total"] if "total" in updates else working.total
        pair_total = resolved_total if isinstance(resolved_total, Decimal) or resolved_total is None else None
        pair = reconcile_currency_total_pair(
            currency=str(resolved_currency or ""),
            total=pair_total,
            text=ocr_text,
        )
        if pair.multi_currency or pair.swapped or pair.reason.startswith("filled_"):
            cur_now = (str(resolved_currency or "")).strip().upper()
            if "currency" not in skip and pair.currency != cur_now:
                updates["currency"] = pair.currency
                grounding_debug["currency_total_pair"] = pair.reason
            if "total" not in skip and pair.total != pair_total:
                updates["total"] = pair.total
                grounding_debug["currency_total_pair"] = pair.reason

    bsb = validate_bank_bsb(data.bank_bsb, ocr_text)
    account = validate_bank_account(data.bank_account, ocr_text)
    if (data.bank_bsb or "").strip() != (bsb or ""):
        updates["bank_bsb"] = bsb
    if (data.bank_account or "").strip() != (account or ""):
        updates["bank_account"] = account

    extracted = ground_extracted_fields_map(
        extracted_fields_from_parsed(data),
        ocr_text,
        grounding_debug=grounding_debug,
    )
    if extracted != extracted_fields_from_parsed(data):
        updates["extracted_fields"] = extracted

    if grounding_debug:
        raw = dict(data.raw_fields or {})
        raw["_grounding_debug"] = grounding_debug
        updates["raw_fields"] = raw

    if not updates:
        return data
    return replace(data, **updates)


def ground_parsed_fields(
    parsed: InvoiceData,
    ocr_text: str | None,
    selected_keys: Sequence[str],
    ocr_payload: dict[str, object] | None = None,
    *,
    trace: object | None = None,
    org_country: str | None = None,
) -> InvoiceData:
    """Filter and ground parsed extraction output before OCR backfill."""
    from app.services.extraction.extraction_field_values import (
        clear_llm_scalars_for_di_populated_fields,
        filter_parsed_to_requested_keys,
        prebuilt_invoice_scalars_active,
    )
    from app.services.extraction.line_items_parser import (
        di_line_items_usable,
        document_has_charge_lines,
        document_has_line_item_table,
    )

    filtered = filter_parsed_to_requested_keys(parsed, selected_keys)
    grounded = ground_invoice_scalars(filtered, ocr_text, org_country=org_country)
    if prebuilt_invoice_scalars_active(ocr_payload):
        grounded = clear_llm_scalars_for_di_populated_fields(
            grounded, selected_keys, ocr_payload, ocr_text=ocr_text
        )
    selected = {str(key or "").strip().lower() for key in selected_keys if str(key or "").strip()}
    if "line_items" in selected:
        payload = ocr_payload or {}
        if di_line_items_usable(payload):
            if trace is not None:
                trace.record("*", "grounding", "modified", "di_rows_authoritative")
            grounded = replace(grounded, line_items_grounding="ungrounded")
        elif not document_has_line_item_table(ocr_text, payload) and not document_has_charge_lines(
            ocr_text
        ):
            if trace is not None:
                trace.record("*", "grounding", "modified", "no_line_item_table_signal")
            grounded = replace(grounded, line_items_grounding="unverifiable")
        else:
            grounded = replace(grounded, line_items_grounding="grounded")
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
