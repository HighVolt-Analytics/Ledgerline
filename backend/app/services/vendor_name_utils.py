"""Heuristics for rejecting bad vendor strings from OCR / Document Intelligence."""

from __future__ import annotations

import re

from app.services.document_heading_utils import is_doc_title_line, strip_doc_title_from_line

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

_COMPANY_SUFFIX = re.compile(
    r"^(.+?\b(?:Pty\.?\s*Ltd\.?|Pvt\s+Ltd\.?|Limited|Ltd\.?|Inc\.?|Corp\.?|"
    r"Corporation|Company|Co\.?|LLC|GmbH|PLC))\b",
    re.I,
)

_ADDRESSish_LINE = re.compile(
    r"^\d+\s+\w+|(?:\broad\b|\bstreet\b|\bavenue\b|\bdrive\b|\bnsw\b|\bvic\b|\bqld\b).*\d{4}\b",
    re.I,
)


def is_plausible_vendor_name(value: str | None) -> bool:
    """Reject payment footers and other non-vendor strings from OCR/DI."""
    if not value or not str(value).strip():
        return False
    text = re.sub(r"\s+", " ", str(value).strip())
    if len(text) < 3 or len(text) > 80:
        return False
    if _VENDOR_REJECT_RE.search(text):
        return False
    if _LABEL_FRAGMENT.match(text):
        return False
    lower = text.lower()
    if lower.startswith(("invoice date", "due date", "abn:", "abn ")):
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
    """Supplier on PO / GRN layouts (Vendor/Supplier or Supplier Details blocks)."""
    patterns = (
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


def normalize_vendor_name(value: str | None) -> str | None:
    if not value:
        return None
    deduped = dedupe_repeated_vendor_phrase(str(value))
    if not is_plausible_vendor_name(deduped):
        return None
    return re.sub(r"\s+", " ", deduped.strip())


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


def pick_best_vendor_name(*candidates: str | None) -> str | None:
    best: str | None = None
    for candidate in candidates:
        normalized = normalize_vendor_name(candidate)
        if not normalized:
            continue
        if best is None or len(normalized) > len(best):
            best = normalized
    return best
