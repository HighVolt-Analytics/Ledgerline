"""SO reference plausibility — filters OCR junk before sales routing."""

from __future__ import annotations

import re

_SO_PREFIX = re.compile(r"^SO[-\s#]?", re.IGNORECASE)

_SO_TEXT_PATTERNS = (
    re.compile(
        r"Sales\s*Order\s+(?:No\.?|Number)\s*[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})",
        re.I,
    ),
    re.compile(
        r"Sales\s*Order\s*(?:No\.?|Number|#)?[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})",
        re.I,
    ),
    re.compile(r"SO\s*Reference[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})", re.I),
    re.compile(
        r"(?:^|\n)\s*S\.?O\.?\s*(?:No\.?|Number|#)?[:\s#]+([A-Z0-9][A-Z0-9\-/_]{2,})",
        re.I,
    ),
    re.compile(
        r"\bNo\.?\s*[:\s#]+(SO[-\s][A-Z0-9][A-Z0-9\-/_]{2,})",
        re.I,
    ),
)


_SO_FILENAME_PATTERNS = (
    re.compile(
        r"(?:sales[_\s-]?order|salesorder)[_\s-]+([A-Z0-9][A-Z0-9\-/_]{2,})",
        re.I,
    ),
    re.compile(r"(?:^|[_\-.])(SO[-\s#][A-Z0-9][A-Z0-9\-/_]{2,})(?:[_\-.]|$)", re.I),
    re.compile(r"(?:^|[_\-.])(SO[0-9][A-Z0-9\-/_]{2,})(?:[_\-.]|$)", re.I),
)


def is_plausible_so_reference(so: str | None) -> bool:
    """True when SO text looks like a real reference (not OCR noise)."""
    if not so or not so.strip():
        return False
    text = so.strip()
    if len(text) < 4:
        return False
    if _SO_PREFIX.match(text):
        return True
    if re.search(r"\d", text):
        return True
    return False


def effective_so_reference(so: str | None) -> str | None:
    if is_plausible_so_reference(so):
        return (so or "").strip()
    return None


def extract_so_reference_from_text(text: str | None) -> str | None:
    """Best-effort SO number from OCR body (sales-order layouts)."""
    if not text or not text.strip():
        return None
    for pattern in _SO_TEXT_PATTERNS:
        match = pattern.search(text)
        if match:
            candidate = match.group(1).strip()
            if is_plausible_so_reference(candidate):
                return candidate
    return None


def extract_so_reference_from_filename(filename: str | None) -> str | None:
    """Best-effort SO number from upload filename (sales_order_SO-100.pdf)."""
    if not filename or not filename.strip():
        return None
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", stem)
    for pattern in _SO_FILENAME_PATTERNS:
        match = pattern.search(stem)
        if not match:
            continue
        candidate = match.group(1).strip()
        if is_plausible_so_reference(candidate):
            return candidate
    return None


def _so_from_extracted_fields(invoice) -> str | None:
    fields = getattr(invoice, "extracted_fields", None) or {}
    if not isinstance(fields, dict):
        return None
    for key in ("so_reference", "sales_order", "sales_order_no", "so_number"):
        token = str(fields.get(key) or "").strip()
        if is_plausible_so_reference(token):
            return token
    return None


def resolve_so_reference_from_invoice(invoice) -> str | None:
    """Resolved SO linkage key from column, extracted fields, filename, or body."""
    direct = effective_so_reference(getattr(invoice, "so_reference", None))
    if direct:
        return direct

    extracted = _so_from_extracted_fields(invoice)
    if extracted:
        return extracted

    attach = getattr(invoice, "email_attachment_name", None)
    from_file = extract_so_reference_from_filename(attach)
    if from_file:
        return from_file

    body = getattr(invoice, "document_text", None)
    from_text = extract_so_reference_from_text(body)
    if from_text:
        return from_text

    invoice_no = str(getattr(invoice, "invoice_no", None) or "").strip()
    if is_plausible_so_reference(invoice_no) and _SO_PREFIX.match(invoice_no):
        return invoice_no

    from_po = getattr(invoice, "po_reference", None)
    if is_plausible_so_reference(from_po):
        return (from_po or "").strip()

    return None


def ensure_invoice_so_reference(invoice) -> str | None:
    """Populate invoice.so_reference when a plausible key can be inferred."""
    resolved = resolve_so_reference_from_invoice(invoice)
    if resolved:
        invoice.so_reference = resolved
    return resolved


def sanitize_cross_book_linkage_references(invoice) -> None:
    """Clear PO column when it holds a sales-order key (common on AR uploads)."""
    po = str(getattr(invoice, "po_reference", None) or "").strip()
    if not po:
        return
    from app.services.po_reference import is_plausible_po_reference

    if is_plausible_so_reference(po) and not is_plausible_po_reference(po):
        invoice.po_reference = None
        return
    so = str(getattr(invoice, "so_reference", None) or "").strip()
    route = str(getattr(invoice, "route_target", None) or "").strip()
    if route == "Sales Management" and so and po.upper() == so.upper():
        invoice.po_reference = None
