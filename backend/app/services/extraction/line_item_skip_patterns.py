"""Shared line-item skip patterns for parser, sanitizer, and frontend parity."""

from __future__ import annotations

import re

# Extracted-field keys whose values must not appear as product line descriptions.
HEADER_DEDUP_EXTRACTED_FIELD_KEYS: tuple[str, ...] = (
    "seller_name",
    "buyer_name",
    "seller_tax_id",
    "buyer_tax_id",
    "seller_abn",
    "buyer_abn",
    "billing_address",
    "document_heading",
    "so_reference",
    "cost_centre",
    "consignment_ref",
    "permit_no",
    "bank_name",
    "bank_bsb",
    "bank_account",
    "customer",
    "delivery_date",
)

# Optional prefix for money columns in OCR line-item rows (shared with frontend invoicePreview.ts).
from app.services.extraction.line_item_header_vocab import TABLE_HEADER_CELL_RE as _TABLE_HEADER  # noqa: E402
from app.services.extraction.locale_vocab import OPTIONAL_CURRENCY_MONEY_PREFIX  # noqa: E402,F401

__all__ = (
    "HEADER_DEDUP_EXTRACTED_FIELD_KEYS",
    "OPTIONAL_CURRENCY_MONEY_PREFIX",
    "has_trusted_line_items",
    "is_metadata_line_description",
    "is_ocr_noise_line_description",
    "is_summary_line_description",
    "should_skip_line_row",
)
# Known header / party / payment labels (label-only or Label: value).
_HEADER_LABEL_TOKEN = (
    r"customer|ship(?:ped)?\s*(?:to|date|qty|ped)?|delivery\s*date|invoice\s*(?:no|number|#|date)|"
    r"po\s*(?:no|number|reference)?|order\s*(?:no|number)?|so\s*(?:no|number|reference)?|"
    r"bill(?:ed)?\s*to|ship\s*to|vendor|supplier|abn|gstin|bsb|account\s*(?:no|number|name)?|"
    r"payment\s*terms|due\s*date|date\s*paid|receipt\s*(?:no|number)?|"
    r"consignment|permit|cost\s*cent(?:er|re)|currency|ccy|curr|"
    r"phone|tel(?:ephone)?(?:\s*no\.?)?|mobile|email|fax|address|attn|attention|"
    r"bank(?:\s*name)?|swift|iban|remittance|page\s*\d+(?:\s*of\s*\d+)?"
)

# Metadata field labels that must never appear as product line rows (label only).
_METADATA_LABEL = re.compile(
    rf"^(?:{_HEADER_LABEL_TOKEN})\s*:?\s*$",
    re.I,
)

# Header Label: value (colon required for ambiguous labels like customer/vendor).
_METADATA_LABEL_VALUE_COLON = re.compile(
    rf"^(?:{_HEADER_LABEL_TOKEN})\s*:\s*\S",
    re.I,
)

# Space/dash form only for unambiguous document headers (OCR often drops ':').
_METADATA_LABEL_VALUE_SPACE = re.compile(
    r"^(?:"
    r"invoice\s*(?:no|number|#|date)|"
    r"po\s*(?:no|number|reference)?|"
    r"so\s*(?:no|number|reference)?|"
    r"order\s*(?:no|number)?|"
    r"ship\s*to|bill(?:ed)?\s*to|"
    r"due\s*date|delivery\s*date|ship(?:ped)?\s*date|"
    r"payment\s*terms|abn|gstin|bsb|"
    r"currency|ccy|curr|"
    r"cost\s*cent(?:er|re)|"
    r"account\s*(?:no|number|name)"
    r")\s*(?:-+|\s+)\S",
    re.I,
)

# Phone / fax fragments (e.g. "Tel No:+91" from OCR header bleed into line tables).
_PHONE_LINE = re.compile(
    r"^(?:tel(?:ephone)?|phone|mobile|fax)\s*(?:no\.?|number|#)?\s*:?\s*\+?\d",
    re.I,
)

# OCR noise posing as a product description (digit codes, colon-separated IDs).
_OCR_NOISE_LINE = re.compile(
    r"^(?:"
    r"\d{3,}(?:\s*[:#/\-]\s*\d+)+\s*"  # 005422: 27054
    r"|[A-Z]{0,3}\d{4,}(?:\s*[:#/\-]\s*\d+)+\s*"
    r"|\d+(?:\s+\d+){2,}\s*"  # bare digit runs only
    r")$",
    re.I,
)

_SUMMARY_MONEY_FOOTER = re.compile(
    r"^(?:"
    r"(?:grand\s+)?(?:sub\s*)?total(?:\s+(?:gst|tax|excl(?:uding)?\s*gst|incl(?:uding)?\s*gst))?|"
    r"total\s+(?:gst|tax|amount|due)|"
    r"amount\s*(?:due|payable)|"
    r"balance\s*(?:due|owing)|"
    r"net\s*(?:payable|amount|total)|"
    r"(?:gst|tax)\s*(?:amount|total)?|"
    # Tax / adjustment footers (label ± amount) — not product rows
    r"(?:[csi]?gst|igst|utgst|vat|cess)\s*@\s*[\d.]+%?|"
    r"round\s*off|"
    r"taxable\s*(?:amount|value)|"
    r"(?:freight|discount)\s*totals?"
    r")\b"
    r"(?:\s*:?\s*\$?\s*[\d,]+\.?\d*)?\s*$",
    re.I,
)

_BANK_REMITTANCE_LINE = re.compile(
    r"\b(?:bank\s*(?:details|name|account)|account\s*name|bsb|swift|iban|"
    r"remittance\s*(?:advice|to)|please\s*remit|payment\s*to)\b",
    re.I,
)


def is_summary_line_description(desc: str | None) -> bool:
    """True when description is a totals/summary row, not a product line."""
    text = re.sub(r"\s+", " ", (desc or "").strip())
    if not text:
        return True
    if re.match(r"^sub\s*total\s*:?\s*$", text, re.I):
        return True
    if re.match(r"^(?:grand\s+)?totals?\s*:?\s*$", text, re.I):
        return True
    if re.match(r"^(?:gst|tax)\s*:?\s*$", text, re.I):
        return True
    # CGST/SGST/IGST/CESS rate or bare tax labels (label only or label + amount).
    if re.match(
        r"^(?:[csi]?gst|igst|utgst|vat|cess)(?:\s*@\s*[\d.]+%?)?"
        r"(?:\s*:?\s*\$?\s*[\d,]+\.?\d*)?$",
        text,
        re.I,
    ):
        return True
    if re.match(
        r"^(?:round\s*off|taxable\s*(?:amount|value)|(?:freight|discount)\s*totals?)"
        r"(?:\s*:?\s*\$?\s*[\d,]+\.?\d*)?$",
        text,
        re.I,
    ):
        return True
    if re.search(r"\b(?:total\s+no\.?\s+of\s+pallet|no\.?\s+of\s+pallet|pallet\s*:)\b", text, re.I):
        return True
    if re.search(r"\b(?:total\s*due|amount\s*due)\b", text, re.I):
        return True
    if re.match(r"^abn\s*:?\s*\d", text, re.I):
        return True
    # Money-bearing footer labels with optional trailing amount only
    if _SUMMARY_MONEY_FOOTER.match(text):
        return True
    if _BANK_REMITTANCE_LINE.search(text) and len(text) <= 120:
        return True
    return False


def is_ocr_noise_line_description(desc: str | None) -> bool:
    """True when description is OCR digit/code noise, not a product name."""
    text = re.sub(r"\s+", " ", (desc or "").strip())
    if not text:
        return False
    if _OCR_NOISE_LINE.match(text):
        return True
    letters = sum(1 for ch in text if ch.isalpha())
    digits = sum(1 for ch in text if ch.isdigit())
    # Table row index / fragment (e.g. "209") misread as the product description.
    if letters == 0 and re.fullmatch(r"\d{1,4}", text):
        return True
    if digits >= 6 and letters <= 1 and len(text) <= 40:
        return True
    if digits >= 4 and letters == 0:
        return True
    return False


def is_metadata_line_description(desc: str | None) -> bool:
    """True when description is a header/metadata label, not a product line."""
    text = re.sub(r"\s+", " ", (desc or "").strip())
    if not text:
        return True
    if text.endswith(":") and len(text) <= 40:
        return True
    if _METADATA_LABEL.match(text):
        return True
    if _METADATA_LABEL_VALUE_COLON.match(text):
        return True
    if _METADATA_LABEL_VALUE_SPACE.match(text):
        return True
    if _TABLE_HEADER.match(text):
        return True
    if _PHONE_LINE.match(text):
        return True
    # Multi-cell OCR header bleed: "Description Qty Unit Price Amount"
    if re.match(
        r"^(?:description|item|product|name|particulars?)\b.+\b(?:qty|quantity|amount|unit\s*price|rate|accepted)\b",
        text,
        re.I,
    ) and len(text.split()) <= 10:
        return True
    return False


def should_skip_line_row(
    desc: str | None,
    *,
    trace: object | None = None,
    row_key: str | None = None,
) -> bool:
    """Combined skip check used by parser and sanitizer."""
    if is_summary_line_description(desc):
        if trace is not None and row_key:
            trace.record(row_key, "skip_pattern", "dropped", "summary_row")
        return True
    if is_metadata_line_description(desc):
        if trace is not None and row_key:
            trace.record(row_key, "skip_pattern", "dropped", "metadata_label")
        return True
    return False


def has_trusted_line_items(items: list) -> bool:
    """True when at least one row looks like a real product line with money."""
    for item in items:
        desc = getattr(item, "description", None)
        if not str(desc).strip() or should_skip_line_row(str(desc)):
            continue
        if getattr(item, "amount", None) is not None or getattr(item, "unit_price", None) is not None:
            return True
    return False
