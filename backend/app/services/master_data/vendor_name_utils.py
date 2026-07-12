"""Heuristics for rejecting bad vendor strings from OCR / Document Intelligence."""

from __future__ import annotations

import re

from app.services.extraction.document_heading_utils import is_doc_title_line, strip_doc_title_from_line

_VENDOR_REJECT_RE = re.compile(
    r"payment\s+terms|please\s+reference|gst\s+is\s+charged|net\s+\d+\s+days|"
    r"amount\s+due|total\s+due|bank\s+details|remit\s+to|thank\s+you|"
    r"invoice\s+number\s+with\s+payment",
    re.I,
)

_HEADER_VENDOR_STOP = re.compile(
    r"^(?:TAX\s+INVOICE|INVOICE|BILL\s+TO|SHIP\s+TO|ABN\b|GSTIN\b|PURCHASE\s+ORDER|"
    r"GOODS\s+RECEIPT|DESCRIPTION\b|CURRENCY\b|VENDOR\b|SUPPLIER\b|DETAILS\b|RECEIVED\b)",
    re.I,
)

_LABEL_FRAGMENT = re.compile(
    r"^(?:/|vendor|supplier|details|received|ship\s+to|bill\s+to|ship\s+to\b|"
    r"supplier\s+details?|vendor\s*/?\s*supplier|name\b)",
    re.I,
)

_FIELD_LABEL_VENDOR = re.compile(
    r"^(?:po|purchase\s+order|invoice|tax\s+invoice|grn|goods\s+receipt|"
    r"delivery\s+note|credit\s+note|debit\s+note|statement|remittance|"
    r"invoice\s+number|po\s+number|grn\s+number|order\s+number|date|due\s+date|"
    r"invoice\s+date|abn|gst|total|subtotal|amount|qty|quantity|line|description|"
    r"bill\s+to|ship\s+to|received\s+at)(?:\s*number)?\s*:?\s*$",
    re.I,
)

_COMPANY_SUFFIX = re.compile(
    r"^(.+?\b(?:Pty\.?\s*Ltd\.?|Pvt\s+Ltd\.?|Limited|Ltd\.?|Inc\.?|Corp\.?|"
    r"Corporation|Company|Co\.?|LLC|GmbH|PLC))\b",
    re.I,
)

_ADDRESSish_LINE = re.compile(
    r"^\d+\s+\w+|(?:\broad\b|\bstreet\b|\bavenue\b|\bdrive\b|\bnsw\b|\bvic\b|\bqld\b).*\d{4}\b",
    re.I,
)

_FORM_LABEL_MARKERS = (
    "pre-carriage",
    "pre carriage",
    "place of",
    "port of",
    "vessel",
    "notify party",
    "consignee",
    "shipper",
    "freight payable",
    "marks and numbers",
)

# Role prefixes glued onto real company names by OCR/layout — strip then keep remainder.
# Longest-first. Transport form markers stay reject-only in is_plausible (not listed here).
_ROLE_PREFIX_STRIP = (
    "notify party",
    "consignee",
    "shipper",
    "applicant",
    "importer",
    "customer",
    "client",
    "buyer",
    "seller",
)

_PACKING_QTY_SUFFIX = re.compile(
    r"(?:=>|->|:|-|–|—|x)\s*\d+(?:[.,]\d+)?\s*"
    r"(?:cartons?|units?|pcs?|pieces?|boxes?|pallets?|kgs?|lbs?)\s*$",
    re.I,
)

_TRAILING_PLOT = re.compile(r"\s+Plot\s+\d+,?\s*$", re.I)

_DOC_REFERENCE_NAME = re.compile(
    r"^(?:GRN|PO|INV|SO|DN|RCP|DEL|ORDER)(?:[\s#:_-]+|\s*number\s*:?\s*)[\w-]*\d",
    re.I,
)

# Standalone dates mis-extracted as vendor (e.g. invoice_date / due_date bleed).
_DATE_ONLY_VENDOR = re.compile(
    r"^(?:"
    r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}"  # 01/07/2026, 15-06-26
    r"|\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2}"  # 2026-07-01
    r"|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}"  # 1 July 2026
    r"|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4}"  # July 1, 2026
    r")$"
)


def strip_vendor_name_contamination(value: str) -> str:
    """Remove role-prefix / packing / address bleed; never invent a name."""
    text = re.sub(r"\s+", " ", str(value).strip())
    if not text:
        return text

    lower = text.lower()
    for marker in _ROLE_PREFIX_STRIP:
        if lower == marker:
            return ""
        prefix = f"{marker} "
        if lower.startswith(prefix):
            text = text[len(prefix) :].strip()
            lower = text.lower()
            break

    text = _PACKING_QTY_SUFFIX.sub("", text).strip(" ,;")
    if not text:
        return text

    company = _COMPANY_SUFFIX.match(text)
    if company:
        truncated = company.group(1).strip()
        remainder = text[len(truncated) :].strip(" ,;")
        if truncated and remainder and (
            re.match(r"^Plot\s+\d+", remainder, re.I)
            or _ADDRESSish_LINE.search(remainder)
            or re.match(r"^\d+\s+\w+", remainder)
        ):
            text = truncated

    text = _TRAILING_PLOT.sub("", text).strip(" ,;")
    if "," in text:
        head, _, tail = text.rpartition(",")
        tail = tail.strip()
        if tail and (
            _ADDRESSish_LINE.search(tail)
            or re.match(r"^\d+\s+\w+", tail)
            or re.match(r"^Plot\s+\d+", tail, re.I)
        ):
            text = head.strip(" ,;")

    return text.strip(" ,;")


def is_plausible_vendor_name(value: str | None) -> bool:
    """Reject payment footers and other non-vendor strings from OCR/DI."""
    if not value or not str(value).strip():
        return False
    text = strip_vendor_name_contamination(re.sub(r"\s+", " ", str(value).strip()))
    if not text:
        return False
    if len(text) < 3 or len(text) > 80:
        return False
    if _VENDOR_REJECT_RE.search(text):
        return False
    if _LABEL_FRAGMENT.match(text):
        return False
    if _FIELD_LABEL_VENDOR.match(text):
        return False
    if re.match(r"^(?:po|invoice|grn|order)\s+number\s*:?\s*$", text, re.I):
        return False
    lower = text.lower()
    if any(lower == marker or lower.startswith(f"{marker} ") for marker in _FORM_LABEL_MARKERS):
        return False
    if lower.startswith(("invoice date", "due date", "abn:", "abn ")):
        return False
    if _DOC_REFERENCE_NAME.match(text):
        return False
    if _DATE_ONLY_VENDOR.match(text):
        return False
    if text.count(".") >= 1 and len(text) > 55:
        return False
    if len(text.split()) > 10:
        return False
    return True


def dedupe_repeated_vendor_phrase(value: str) -> str:
    """Collapse OCR duplicates like 'Acme Pty Ltd Acme Pty Ltd'."""
    text = re.sub(r"\s+", " ", value.strip())
    if not text:
        return text
    words = text.split()
    if len(words) >= 4 and len(words) % 2 == 0:
        mid = len(words) // 2
        left = " ".join(words[:mid])
        right = " ".join(words[mid:])
        if left.lower() == right.lower():
            return left
    half = len(text) // 2
    if half >= 3 and text[:half].strip().lower() == text[half:].strip().lower():
        return text[:half].strip()
    return text


def _clean_party_line(line: str) -> str:
    cleaned = re.sub(r"^[/\s]+", "", line.strip())
    cleaned = re.split(
        r"\b(?:Ship\s+To|Bill\s+To|Received\s+At)\b",
        cleaned,
        maxsplit=1,
        flags=re.I,
    )[0].strip()
    match = _COMPANY_SUFFIX.match(cleaned)
    if match:
        return match.group(1).strip()
    return cleaned


def extract_supplier_party_from_text(text: str) -> str | None:
    """Supplier on PO / GRN / invoice layouts (Vendor/Supplier blocks)."""
    patterns = (
        r"Vendor[:\s]+\n\s*([^\n]+)",
        r"Vendor[:\s]+([^\n]+)",
        r"(?:Vendor\s*/?\s*Supplier|Supplier\s+Details?)(?:[^\n]*)?\n\s*([^\n]+)",
        r"Bill\s+From[:\s]+([^\n]+)",
        r"Remit\s+To[:\s]+([^\n]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        candidate = _clean_party_line(match.group(1))
        if _LABEL_FRAGMENT.match(candidate):
            continue
        normalized = normalize_vendor_name(candidate)
        if normalized:
            return normalized
    return None


def extract_customer_party_from_text(text: str) -> str | None:
    """Customer on sales invoice layouts (Bill To / Sold To / Customer blocks)."""
    patterns = (
        r"(?:Bill\s+To|Sold\s+To|Customer|Client)(?:[^\n]*)?\n\s*([^\n]+)",
        r"(?:Bill\s+To|Sold\s+To|Customer|Client)[:\s]+([^\n]+)",
        r"Ship\s+To[:\s]+([^\n]+)",
        r"APPLICANT'?S?\s+NAME[:\s]+([^\n]+)",
        r"Consignee[:\s]+([^\n]+)",
        r"Importer[:\s]+([^\n]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        candidate = _clean_party_line(match.group(1))
        if _LABEL_FRAGMENT.match(candidate):
            continue
        normalized = normalize_vendor_name(candidate)
        if normalized:
            return normalized
    return None


def normalize_vendor_name(value: str | None) -> str | None:
    if not value:
        return None
    deduped = dedupe_repeated_vendor_phrase(str(value))
    cleaned = strip_vendor_name_contamination(deduped)
    if not is_plausible_vendor_name(cleaned):
        return None
    return re.sub(r"\s+", " ", cleaned.strip())


def extract_header_vendor(text: str) -> str | None:
    """First plausible supplier line before bill-to / tax invoice blocks."""
    for line in text.splitlines()[:25]:
        candidate = strip_doc_title_from_line(line)
        if not candidate:
            continue
        if _HEADER_VENDOR_STOP.match(candidate):
            break
        if is_doc_title_line(candidate):
            continue
        if _ADDRESSish_LINE.search(candidate) and re.search(r"\d", candidate):
            continue
        normalized = normalize_vendor_name(candidate)
        if normalized:
            return normalized
    return None


def extract_buyer_party_from_text(text: str) -> str | None:
    """Buyer / consignee / applicant on import and sales layouts."""
    return extract_customer_party_from_text(text)


def _collapse_address_block(raw: str) -> str:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    return " ".join(lines)


def extract_buyer_address_from_text(text: str) -> str | None:
    """Bill-to / applicant / consignee address blocks."""
    patterns = (
        r"APPLICANT'?S?\s+ADDRESS[:\s]*\n?([^\n]+(?:\n[^\n]+){0,3})",
        r"(?:Bill\s+To|Ship\s+To|Sold\s+To|Consignee|Importer)(?:[^\n]*)?\n\s*([^\n]+(?:\n[^\n]+){0,3})",
        r"(?:Bill\s+To|Ship\s+To|Consignee)[:\s]+([^\n]+(?:\n[^\n]+){0,2})",
        # Commercial invoice addressee block before DATE
        r"COMMERCIAL\s+INVOICE\s*\n\s*([A-Z][^\n]+(?:\n[^\n]+){1,3})\s*\n\s*DATE\s*:",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.M)
        if not match:
            continue
        candidate = _collapse_address_block(match.group(1))
        if len(candidate) >= 12:
            return candidate[:500]
    return None


def extract_seller_address_from_text(text: str) -> str | None:
    """Exporter / supplier address from letterhead or vendor blocks."""
    patterns = (
        r"(?:Bill\s+From|Remit\s+To|Exporter|Supplier\s+Address)[:\s]*\n?([^\n]+(?:\n[^\n]+){0,2})",
        r"(?:Bill\s+From|Exporter)[:\s]+([^\n]+(?:\n[^\n]+){0,2})",
        # Letterhead address line after company name (intl postcodes 4-6 digits)
        r"^([A-Z0-9][^\n]*(?:\b(?:road|street|avenue|drive|rd|st)\b)[^\n]*\d{4,6}\b[^\n]*)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.M)
        if not match:
            continue
        candidate = _collapse_address_block(match.group(1))
        if len(candidate) >= 8:
            return candidate[:500]
    return None


def pick_best_vendor_name(*candidates: str | None) -> str | None:
    best: str | None = None
    for candidate in candidates:
        normalized = normalize_vendor_name(candidate)
        if not normalized:
            continue
        if best is None or len(normalized) > len(best):
            best = normalized
    return best
