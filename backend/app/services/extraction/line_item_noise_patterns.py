"""Configurable noise heuristics for line-item rows from loose OCR text."""

from __future__ import annotations

import re
from decimal import Decimal

ADDRESS_LIKE = re.compile(
    r"\b(?:street|st\.?|road|rd\.?|avenue|ave\.?|drive|dr\.?|lane|ln\.?|boulevard|blvd\.?|"
    r"straat|gracht|weg|laan|plein|allee|"
    r"suite|floor|building|unit\s+\d+|henderson|singapore|postal|zip\s*code|"
    r"australia|nsw|vic|qld|sa|wa|act|tas|nz|new\s+zealand)\b",
    re.I,
)
POSTAL_RUN = re.compile(r"\b\d{4,6}\b")

REFERENCE_BLOCK = re.compile(
    r"\b(?:DOCUMENTARY\s+CREDIT|CERTIFICATE|REFERENCE\s+NO|CONTRACT\s+NO|IRC\s+NO|TIN\b|BIN\s+NO)\b",
    re.I,
)

BANK_CONTACT = re.compile(
    r"\b(?:bank\s*(?:details|name|account)|account\s*name|bsb|swift|iban|"
    r"remittance|please\s*(?:pay|remit)|payment\s*instructions|"
    r"tel(?:ephone)?|phone|mobile|fax|email|www\.|http)\b",
    re.I,
)

PAGE_FOOTER = re.compile(
    r"^(?:page\s*\d+(?:\s*of(?:\s*\d+)?)?|continued(?:\s+on\s+next\s+page)?|end\s+of\s+(?:document|invoice))\s*$",
    re.I,
)

# "$45.03 USD due May 1," / "Amount due May 1, 2026" payment banners (not product rows).
AMOUNT_DUE_BANNER = re.compile(
    r"(?:"
    r"^(?:\$|€|£)?\s*[\d,]+\.?\d*\s*(?:[A-Z]{3})?\s*due\b|"
    r"\b(?:amount|balance|total)\s+due\b|"
    r"\bdue\s+(?:on\s+)?(?:\d{1,2}[/\-.]\d{1,2}|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r")",
    re.I,
)

# Street / canal names OCR often splits from address blocks (e.g. Prinsengracht / Prinsengracht 769).
BARE_STREET_TOKEN = re.compile(
    r"^(?:[A-Z][a-z]+(?:straat|gracht|weg|laan|plein|allee|avenue|street|road|drive|lane))"
    r"(?:\s+\d+[A-Za-z]?)?$",
    re.I,
)

PURE_DATE = re.compile(
    r"^(?:\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2}|"
    r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{2,4})$",
    re.I,
)

ABN_GSTIN = re.compile(
    r"^(?:abn|gstin|acn|tfn)\s*:?\s*[\d\s]{8,}|^\d{2}\s?\d{3}\s?\d{3}\s?\d{3}$|"
    r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d]$",
    re.I,
)

PHONE_FRAGMENT = re.compile(
    r"^(?:tel(?:ephone)?|phone|mobile|fax)\s*(?:no\.?|number|#)?\s*:?\s*\+?[\d\s\-()]{6,}$|"
    r"^\+?\d[\d\s\-()]{7,}$",
    re.I,
)

BARE_CODE_TOKEN = re.compile(r"^[A-Z0-9][A-Z0-9\-/_]{1,20}$", re.I)

# UOM bleed from GRN qty cells ("60 Box", "195 Pair") — not product descriptions.
BARE_QTY_UOM = re.compile(
    r"^\d+(?:[.,]\d+)?\s*(?:box|pair|pcs|nos?|ea|kg|tray|plt|pallet|units?|packs?)$",
    re.I,
)


def is_noise_line_item_row(
    description: str | None,
    qty: Decimal | None = None,
    *,
    trace: object | None = None,
    row_key: str | None = None,
) -> bool:
    """True when a row looks like address/reference/metadata rather than a product line."""
    desc = (description or "").strip()
    if not desc:
        return True

    def _drop(reason: str) -> bool:
        if trace is not None and row_key:
            trace.record(row_key, "noise", "dropped", reason)
        return True

    if REFERENCE_BLOCK.search(desc):
        return _drop("reference_block")
    if PAGE_FOOTER.match(desc):
        return _drop("page_footer")
    if AMOUNT_DUE_BANNER.search(desc):
        return _drop("amount_due_banner")
    if PURE_DATE.match(desc):
        return _drop("pure_date")
    if ABN_GSTIN.match(desc):
        return _drop("abn_gstin")
    if PHONE_FRAGMENT.match(desc):
        return _drop("phone_fragment")
    if BANK_CONTACT.search(desc) and len(desc.split()) <= 14:
        return _drop("bank_contact")
    if ADDRESS_LIKE.search(desc) and POSTAL_RUN.search(desc):
        return _drop("address_like")
    if ADDRESS_LIKE.search(desc) and len(desc.split()) <= 8:
        return _drop("address_like")
    if BARE_STREET_TOKEN.match(desc):
        return _drop("bare_street")
    if BARE_CODE_TOKEN.match(desc) and qty is not None and qty > Decimal("10000"):
        return _drop("bare_code_qty")
    if BARE_QTY_UOM.match(desc):
        return _drop("bare_qty_uom")
    words = [word for word in re.split(r"\s+", desc) if word]
    if len(words) <= 3 and qty is not None and qty > Decimal("1000"):
        if not re.search(r"\b(?:cpu|chip|part|widget|item|unit|kg|pcs)\b", desc, re.I):
            return _drop("short_high_qty")
    return False
