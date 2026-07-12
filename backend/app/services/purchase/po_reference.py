"""PO reference plausibility — filters OCR junk before purchase routing."""

from __future__ import annotations

import re

_PO_PREFIX = re.compile(r"^PO[-\s#]?", re.IGNORECASE)

_PO_TEXT_PATTERNS = (
    re.compile(
        r"Purchase\s*Order\s+(?:No\.?|Number)\s*[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})",
        re.I,
    ),
    re.compile(
        r"Purchase\s*Order\s*(?:No\.?|Number|#)?[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})",
        re.I,
    ),
    re.compile(r"PO\s*Reference[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})", re.I),
    re.compile(
        r"(?:^|\n)\s*P\.?O\.?\s*(?:No\.?|Number|#)?[:\s#]+([A-Z0-9][A-Z0-9\-/_]{2,})",
        re.I,
    ),
    re.compile(
        r"\bNo\.?\s*[:\s#]+(PO[-\s][A-Z0-9][A-Z0-9\-/_]{2,})",
        re.I,
    ),
)


_SO_PREFIX = re.compile(r"^SO[-\s#]?", re.IGNORECASE)


def is_plausible_po_reference(po: str | None) -> bool:
    """True when PO text looks like a real reference (not OCR noise like 'the')."""
    from app.services.shared.reference_field_sanitizer import has_multiline_text

    if not po or not po.strip():
        return False
    text = po.strip()
    if has_multiline_text(text):
        return False
    if len(text) > 64:
        return False
    if len(text) < 4:
        return False
    # Sales-order keys must not satisfy PO plausibility (common LLM conflation on AR docs).
    if _SO_PREFIX.match(text):
        return False
    if _PO_PREFIX.match(text):
        return True
    if re.search(r"\d", text):
        return True
    return False


def effective_po_reference(po: str | None) -> str | None:
    if is_plausible_po_reference(po):
        return (po or "").strip()
    return None


def normalize_po_link_token(po: str | None) -> str:
    """Case-folded PO key for sibling / dossier linkage (matches playbook checks)."""
    return (po or "").strip().upper()


def invoice_po_reference_equals(po_reference: str):
    """SQLAlchemy predicate: Invoice.po_reference equals token case-insensitively."""
    from sqlalchemy import func

    from app.models.invoice import Invoice

    token = normalize_po_link_token(po_reference)
    return func.upper(func.coalesce(Invoice.po_reference, "")) == token


def extract_po_reference_from_text(text: str | None) -> str | None:
    """Best-effort PO number from OCR body (purchase-order layouts)."""
    if not text or not text.strip():
        return None
    for pattern in _PO_TEXT_PATTERNS:
        match = pattern.search(text)
        if match:
            candidate = match.group(1).strip()
            if is_plausible_po_reference(candidate):
                return candidate
    return None


def _po_from_extracted_fields(invoice) -> str | None:
    fields = getattr(invoice, "extracted_fields", None) or {}
    if not isinstance(fields, dict):
        return None
    for key in ("po_reference", "purchase_order", "purchase_order_no", "po_number"):
        token = str(fields.get(key) or "").strip()
        if is_plausible_po_reference(token):
            return token
    return None


def resolve_po_reference_from_invoice(invoice) -> str | None:
    """Resolved PO linkage key from column, extracted fields, or body."""
    direct = effective_po_reference(getattr(invoice, "po_reference", None))
    if direct:
        return direct

    extracted = _po_from_extracted_fields(invoice)
    if extracted:
        return extracted

    body = getattr(invoice, "document_text", None)
    from_text = extract_po_reference_from_text(body)
    if from_text:
        return from_text

    return None


def ensure_invoice_po_reference(invoice) -> str | None:
    """Populate invoice.po_reference when a plausible key can be inferred."""
    from app.services.shared.reference_field_sanitizer import sanitize_reference_for_column

    resolved = resolve_po_reference_from_invoice(invoice)
    column_value = sanitize_reference_for_column(
        resolved,
        max_len=100,
        is_plausible=is_plausible_po_reference,
    )
    if column_value:
        invoice.po_reference = column_value
    elif getattr(invoice, "po_reference", None):
        if not is_plausible_po_reference(invoice.po_reference):
            invoice.po_reference = None
    return resolved
