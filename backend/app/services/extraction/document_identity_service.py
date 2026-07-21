"""Catalogue-driven identity extraction and business fingerprints for dedup/splitting."""

from __future__ import annotations

import json
import re
import tempfile
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_field_keys import CANONICAL_EXTRACTION_FIELD_KEYS
from app.services.extraction.extraction_field_values import custom_extraction_field_keys
from app.services.extraction.layout_field_extractor import extract_key_value_fields
from app.services.extraction.pdf_parser import parse_text_fields
from app.services.extraction.permit_ocr_extractors import extract_permit_fields_from_text
from app.services.extraction.pdf_page_text_service import PdfPageText, extract_pdf_page_texts
from app.services.master_data.vendor_name_utils import normalize_vendor_name
from app.utils.hashing import compute_sha256_bytes

if TYPE_CHECKING:
    from app.schemas.document_layout import DocumentLayoutResult

_IDENTITY_CANONICAL = frozenset(
    {
        "vendor",
        "invoice_no",
        "po_reference",
        "so_reference",
        "total",
        "subtotal",
    }
)

_IDENTITY_SUFFIXES = ("_no", "_ref", "_reference", "_id", "_number")


def is_identity_field_key(key: str) -> bool:
    normalized = (key or "").strip().lower()
    if not normalized or not re.match(r"^[a-z][a-z0-9_]{0,63}$", normalized):
        return False
    if normalized in _IDENTITY_CANONICAL:
        return True
    if normalized in CANONICAL_EXTRACTION_FIELD_KEYS and normalized in {
        "invoice_no",
        "po_reference",
        "so_reference",
        "vendor",
        "total",
        "subtotal",
    }:
        return True
    return any(normalized.endswith(suffix) for suffix in _IDENTITY_SUFFIXES)


def identity_field_keys_from_catalogue(
    document_types: list[DocumentTypeDefinition] | tuple[DocumentTypeDefinition, ...],
) -> list[str]:
    """Union of canonical identity keys and tenant-configured reference fields."""
    keys: set[str] = set(_IDENTITY_CANONICAL)
    keys.update(custom_extraction_field_keys(list(document_types)))
    for defn in document_types:
        if not defn.enabled:
            continue
        for raw in defn.required_fields or []:
            token = str(raw or "").strip().lower()
            if is_identity_field_key(token):
                keys.add(token)
    return sorted(keys)


def _normalize_money(value: str) -> str:
    cleaned = re.sub(r"[^\d.\-]", "", value.replace(",", ""))
    if not cleaned:
        return ""
    try:
        amount = Decimal(cleaned)
        return f"{amount.quantize(Decimal('0.01'))}"
    except (InvalidOperation, ValueError):
        return re.sub(r"[^a-z0-9]", "", value.lower())


def dates_within_tolerance(
    left: date | None,
    right: date | None,
    *,
    days: int = 7,
) -> bool:
    """True if either date is missing, or abs calendar-day delta <= days (no timezone)."""
    if left is None or right is None:
        return True
    return abs((left - right).days) <= days


def normalize_identity_value(key: str, value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if key in {"total", "subtotal", "gst"}:
        return _normalize_money(text)
    if key == "vendor":
        # normalize_vendor_name returns None for implausible labels (BUYER, dates, etc.)
        vendor = normalize_vendor_name(text)
        return vendor.lower() if vendor else ""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def extract_identity_fields(
    text: str,
    *,
    custom_field_keys: list[str] | None = None,
    layout: DocumentLayoutResult | None = None,
) -> dict[str, str]:
    """Harvest identity-bearing fields from OCR/layout using existing parsers."""
    allowed = set(custom_field_keys or []) | _IDENTITY_CANONICAL
    fields: dict[str, str] = {}

    parsed = parse_text_fields(text or "")
    for key, value in parsed.items():
        token = str(key or "").strip().lower()
        if token not in allowed or not is_identity_field_key(token):
            continue
        if isinstance(value, str) and value.strip():
            fields[token] = value.strip()
        elif value is not None and token in {"total", "subtotal", "gst"}:
            fields[token] = str(value)

    if layout is not None:
        for key, value in extract_key_value_fields(layout, text or "").items():
            token = str(key or "").strip().lower()
            if token in allowed and is_identity_field_key(token) and value.strip():
                fields.setdefault(token, value.strip())

    for key, value in extract_permit_fields_from_text(text).items():
        token = str(key or "").strip().lower()
        if token in allowed and value.strip():
            fields[token] = value.strip()

    _harvest_fallback_reference_fields(text, fields, allowed)

    return fields


def _harvest_fallback_reference_fields(
    text: str,
    fields: dict[str, str],
    allowed: set[str],
) -> None:
    """Looser reference extraction for split boundaries when strict parsers skip short refs."""
    patterns: tuple[tuple[str, str], ...] = (
        (r"Invoice\s*(?:No\.?|Number|#)\s*[:\s#]*([A-Z0-9][A-Z0-9\-/_]{1,})", "invoice_no"),
        # Seagate/SAP title form: "INVOICE 9300667417" (no "No:" label).
        (r"\bINVOICE\s+([0-9]{7,})\b", "invoice_no"),
        (r"PO\s*(?:Number|No\.?|#|Reference)\s*[:\s#]*([A-Z0-9][A-Z0-9\-/_]{1,})", "po_reference"),
        (r"SO\s*(?:Number|No\.?|#|Reference)\s*[:\s#]*([A-Z0-9][A-Z0-9\-/_]{1,})", "so_reference"),
        # Word-bounded BOL/HAWB — avoid matching inside place names like "Tambol".
        (
            r"(?:Bill\s+of\s+Lading|\bB/?L\b|\bBOL\b|\bHAWB\b|\bMAWB\b|\bAWB\b)\s*"
            r"(?:No\.?|Number|#)?\s*[:.]?\s*([A-Z0-9][A-Z0-9\-]{5,})",
            "bol_no",
        ),
        (r"Freight\s+Order\s*[:.]?\s*([0-9]{6,})", "freight_order_no"),
        (r"Tracking\s*(?:Number|No\.?|#)?\s*[:.]?\s*([A-Z0-9]{10,})", "tracking_no"),
    )
    for pattern, key in patterns:
        if key in fields:
            continue
        # Always allow canonical refs + suffix identity keys (bol_no, freight_order_no, …).
        if key not in allowed and not is_identity_field_key(key):
            continue
        match = re.search(pattern, text or "", re.I)
        if match:
            value = match.group(1).strip()
            if key == "bol_no" and not _looks_like_logistics_ref(value):
                continue
            if value:
                fields[key] = value

    # Bare Seagate-style invoice number on page-1 (OCR often drops the "Invoice No" label).
    if "invoice_no" not in fields and ("invoice_no" in allowed or is_identity_field_key("invoice_no")):
        bare = re.search(
            r"(?im)^(?:invoice\s*)?(9300\d{6})\s*$",
            text or "",
        )
        if bare:
            fields["invoice_no"] = bare.group(1).strip()


def _looks_like_logistics_ref(value: str) -> bool:
    """Reject OCR leftovers mistaken for BOL/HAWB (place names, field labels)."""
    token = (value or "").strip()
    if len(token) < 6:
        return False
    upper = token.upper()
    if upper in {"INCOTERMS", "SUNGNOEN", "SINGAPORE", "FREIGHT", "FORWARDER"}:
        return False
    # Real BOL/HAWB/tracking tokens almost always include a digit.
    return any(ch.isdigit() for ch in token)


def normalize_identity_fields(fields: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in sorted(fields):
        normalized = normalize_identity_value(key, fields[key])
        if normalized:
            out[key] = normalized
    return out


_LINKING_REFERENCE_KEYS = frozenset({"po_reference", "so_reference"})
# Meta keys may be mixed into fingerprint payloads (e.g. document_role) but must not
# alone make a "strong" identity — otherwise all packing lists with no refs collide.
_META_IDENTITY_KEYS = frozenset({"document_role"})


def _has_strong_identity(normalized: dict[str, str]) -> bool:
    """Identity strong enough for business fingerprint (not dossier linking refs alone)."""
    if not normalized:
        return False
    if "invoice_no" in normalized:
        return True
    if "total" in normalized or "subtotal" in normalized:
        return True
    # BOL / HAWB / freight order are strong instrument ids for logistics companions.
    if any(
        key.endswith("_no") or key.endswith("_ref") or key.endswith("_reference")
        for key in normalized
        if key not in _LINKING_REFERENCE_KEYS and key not in _META_IDENTITY_KEYS
    ):
        return True
    non_linking = {
        k
        for k in normalized
        if k not in _LINKING_REFERENCE_KEYS
        and k != "vendor"
        and k not in _META_IDENTITY_KEYS
    }
    if not non_linking:
        return False
    return "vendor" in normalized or len(non_linking) >= 1


def compute_business_fingerprint(fields: dict[str, str]) -> str | None:
    """Stable SHA256 over normalized identity fields."""
    normalized = normalize_identity_fields(fields)
    if not normalized or not _has_strong_identity(normalized):
        return None
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return compute_sha256_bytes(payload.encode("utf-8"))


def extract_identity_fields_from_pages(
    pages: list[PdfPageText],
    *,
    custom_field_keys: list[str] | None = None,
) -> dict[str, str]:
    """Extract identity fields from pre-extracted PDF page text."""
    if not pages:
        return {}
    combined = "\n".join(page.text for page in pages if page.text.strip())
    return extract_identity_fields(combined, custom_field_keys=custom_field_keys)


def compute_business_fingerprint_from_pages(
    pages: list[PdfPageText],
    *,
    custom_field_keys: list[str] | None = None,
) -> str | None:
    fields = extract_identity_fields_from_pages(pages, custom_field_keys=custom_field_keys)
    return compute_business_fingerprint(fields)


def extract_identity_fields_from_pdf_bytes(
    data: bytes,
    *,
    custom_field_keys: list[str] | None = None,
) -> dict[str, str]:
    """Extract identity fields from all pages of a PDF."""
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(data)
            tmp_path = Path(handle.name)
        extraction = extract_pdf_page_texts(tmp_path)
        return extract_identity_fields_from_pages(
            extraction.pages,
            custom_field_keys=custom_field_keys,
        )
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def compute_business_fingerprint_from_bytes(
    data: bytes,
    *,
    custom_field_keys: list[str] | None = None,
) -> str | None:
    fields = extract_identity_fields_from_pdf_bytes(data, custom_field_keys=custom_field_keys)
    return compute_business_fingerprint(fields)


def page_identity_signature(
    text: str,
    *,
    page_kind_token: str | None,
    custom_field_keys: list[str] | None = None,
) -> str | None:
    """Compact boundary signature: kind token + reference fields only."""
    fields = extract_identity_fields(text, custom_field_keys=custom_field_keys)
    normalized = normalize_identity_fields(fields)
    ref_keys = sorted(
        key
        for key in normalized
        if key in {"invoice_no", "po_reference", "so_reference"}
        or key.endswith("_no")
        or key.endswith("_reference")
        or key.endswith("_ref")
    )
    parts: list[str] = []
    if page_kind_token:
        parts.append(page_kind_token)
    for key in ref_keys:
        parts.append(f"{key}={normalized[key]}")
    if not parts:
        return None
    return "|".join(parts)
