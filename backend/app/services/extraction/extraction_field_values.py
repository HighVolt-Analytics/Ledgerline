"""Read/write extraction field values on invoices and parsed OCR payloads."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, TYPE_CHECKING

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_field_keys import (
    CANONICAL_EXTRACTION_FIELD_KEYS,
    is_valid_extraction_field_key,
)
from app.services.invoice.invoice_data import InvoiceData

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.schemas.ocr_artifact import OcrArtifact


def custom_extraction_field_keys(
    document_types: list[DocumentTypeDefinition] | tuple[DocumentTypeDefinition, ...],
) -> list[str]:
    """Non-canonical extraction keys configured across enabled document types."""
    seen: set[str] = set()
    keys: list[str] = []
    for defn in document_types:
        if not defn.enabled:
            continue
        for raw in defn.extraction_fields or []:
            key = raw.strip().lower()
            if not key or key in CANONICAL_EXTRACTION_FIELD_KEYS or key in seen:
                continue
            if not is_valid_extraction_field_key(key):
                continue
            seen.add(key)
            keys.append(key)
    return keys


def custom_extraction_field_keys_for_dt(
    document_types: Sequence[DocumentTypeDefinition],
    dt_code: str,
) -> list[str]:
    """Custom extraction keys configured on one document type (e.g. confirmed DT)."""
    code = (dt_code or "").strip().upper()
    if not code:
        return []
    for defn in document_types:
        if not defn.enabled:
            continue
        if (defn.code or "").strip().upper() != code:
            continue
        keys = custom_extraction_field_keys([defn])
        seen = set(keys)
        for raw in defn.required_fields or []:
            token = str(raw or "").strip().lower()
            if not token or token in CANONICAL_EXTRACTION_FIELD_KEYS or token in seen:
                continue
            if not is_valid_extraction_field_key(token):
                continue
            seen.add(token)
            keys.append(token)
        return keys
    return []


_PRESET_EXTRACTION_LABELS: dict[str, str] = {
    "vendor": "Vendor",
    "abn": "Tax ID / ABN",
    "invoice_no": "Invoice number",
    "invoice_date": "Invoice date",
    "due_date": "Due date",
    "po_reference": "PO reference",
    "so_reference": "SO reference",
    "cost_centre": "Cost centre",
    "subtotal": "Subtotal",
    "gst": "Tax (GST/VAT)",
    "gst_rate": "Tax rate (%)",
    "total": "Total",
    "line_items": "Line items",
    "bank_details": "Bank details",
    "attachment_name": "Attachment name",
    "document_heading": "Document heading",
    "document_text": "Document text (OCR body)",
    "billing_address": "Billing address",
    "seller_name": "Seller name",
    "seller_tax_id": "Seller tax ID",
    "seller_address": "Seller address",
    "buyer_name": "Buyer name",
    "buyer_tax_id": "Buyer tax ID",
    "buyer_address": "Buyer address",
    "email_subject": "Email subject",
    "account_code": "Account code",
    "account_name": "Account name",
}


def extraction_field_label(key: str) -> str:
    token = str(key or "").strip().lower()
    if token in _PRESET_EXTRACTION_LABELS:
        return _PRESET_EXTRACTION_LABELS[token]
    return " ".join(part.capitalize() for part in token.split("_") if part)


def custom_extraction_field_descriptors(keys: Sequence[str]) -> list[dict[str, str]]:
    """Human-readable key + label pairs for LLM custom field extraction."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for raw in keys:
        token = str(raw or "").strip().lower()
        if not token or token in seen or token in CANONICAL_EXTRACTION_FIELD_KEYS:
            continue
        if not is_valid_extraction_field_key(token):
            continue
        seen.add(token)
        out.append({"key": token, "label": extraction_field_label(token)})
    return out


def custom_extraction_fields_prompt_lines(descriptors: list[dict[str, str]]) -> list[str]:
    if not descriptors:
        return []
    lines = [
        "",
        "Custom extraction fields (search OCR for each labeled concept; "
        "put string values in extracted_fields or as top-level keys; do not invent values):",
    ]
    for row in descriptors:
        lines.append(f'- key `{row["key"]}` — label "{row["label"]}"')
    return lines


def normalize_extracted_fields_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        token = str(key or "").strip().lower()
        if not token or not is_valid_extraction_field_key(token):
            continue
        text = str(value or "").strip()
        if text:
            out[token] = text
    return out


def merge_extracted_field_maps(*maps: dict[str, str] | None) -> dict[str, str]:
    merged: dict[str, str] = {}
    for row in maps:
        if not row:
            continue
        for key, value in row.items():
            token = str(key or "").strip().lower()
            text = str(value or "").strip()
            if token and text:
                merged[token] = text
    return merged


def extracted_fields_from_invoice(invoice: object) -> dict[str, str]:
    raw = getattr(invoice, "extracted_fields", None)
    return normalize_extracted_fields_map(raw)


def extracted_fields_from_parsed(parsed: InvoiceData | None) -> dict[str, str]:
    if parsed is None:
        return {}
    from_raw = parsed.raw_fields.get("extracted_fields") if parsed.raw_fields else None
    return normalize_extracted_fields_map(parsed.extracted_fields or from_raw)


def read_extraction_field_value(
    key: str,
    *,
    invoice: Invoice | object,
    parsed: InvoiceData | None = None,
    document_heading: str | None = None,
) -> str | None:
    token = key.strip().lower()
    if not token:
        return None
    if token == "document_heading":
        for candidate in (
            document_heading,
            getattr(invoice, "document_heading", None),
            (parsed.document_heading if parsed else None),
            extracted_fields_from_invoice(invoice).get("document_heading"),
            extracted_fields_from_parsed(parsed).get("document_heading"),
        ):
            text = str(candidate or "").strip()
            if text:
                return text
        return None
    custom = merge_extracted_field_maps(
        extracted_fields_from_invoice(invoice),
        extracted_fields_from_parsed(parsed),
    )
    if token in custom:
        return custom[token]
    if hasattr(invoice, token):
        val = getattr(invoice, token, None)
        if val is not None and str(val).strip():
            return str(val).strip()
    if parsed is not None and hasattr(parsed, token):
        val = getattr(parsed, token, None)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def merge_invoice_extracted_fields(invoice: Invoice, patch: dict[str, str]) -> None:
    """Merge string fields into invoice.extracted_fields (e.g. classification perspective)."""
    cleaned = {k: str(v).strip() for k, v in patch.items() if str(v or "").strip()}
    if not cleaned:
        return
    fields = dict(invoice.extracted_fields or {})
    fields.update(cleaned)
    invoice.extracted_fields = fields


def apply_parsed_extraction_fields(invoice: Invoice, parsed: InvoiceData) -> None:
    from app.services.invoice.invoice_data import _resolved_document_heading

    heading = (parsed.document_heading or _resolved_document_heading(invoice=None, parsed=parsed) or "").strip()[:500]
    if heading:
        parsed.document_heading = heading
    invoice.document_heading = heading or None
    custom = merge_extracted_field_maps(extracted_fields_from_parsed(parsed))
    if heading:
        custom["document_heading"] = heading
    existing = dict(invoice.extracted_fields or {})
    existing.update(custom)
    invoice.extracted_fields = existing or None
    from app.services.sales.so_reference import ensure_invoice_so_reference

    ensure_invoice_so_reference(invoice)


_LLM_RESERVED_RAW_KEYS = frozenset(
    {
        "suggested_dt",
        "confidence",
        "reasoning",
        "perspective",
        "seller",
        "buyer",
        "line_items",
        "field_confidence",
        "extracted_fields",
        "invoice_no",
        "invoice_date",
        "due_date",
        "po_reference",
        "so_reference",
        "cost_centre",
        "subtotal",
        "gst",
        "gst_rate",
        "total",
        "currency",
        "abn",
        "vendor",
        "document_heading",
        "bank_bsb",
        "bank_account",
        "bank_name",
    }
)


def harvest_custom_fields_from_llm_raw(
    raw: dict[str, Any] | None,
    *,
    custom_keys: Sequence[str] | None = None,
) -> dict[str, str]:
    """Collect user-defined field values from LLM JSON (nested or top-level)."""
    if not isinstance(raw, dict):
        return {}
    extracted = normalize_extracted_fields_map(raw.get("extracted_fields"))
    for key in custom_keys or []:
        token = key.strip().lower()
        if not token or token in extracted:
            continue
        nested = raw.get("extracted_fields")
        if isinstance(nested, dict) and nested.get(token):
            extracted[token] = str(nested.get(token)).strip()
            continue
        if token in raw and raw[token] not in (None, "", {}):
            extracted[token] = str(raw[token]).strip()
    for key, value in raw.items():
        token = str(key or "").strip().lower()
        if not token or token in _LLM_RESERVED_RAW_KEYS:
            continue
        if token in CANONICAL_EXTRACTION_FIELD_KEYS:
            continue
        if not is_valid_extraction_field_key(token) or token in extracted:
            continue
        text = str(value or "").strip()
        if text:
            extracted[token] = text
    return extracted


def _scalar_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def enrich_parsed_from_ocr(
    parsed: InvoiceData,
    ocr: OcrArtifact,
    *,
    dt_definition: DocumentTypeDefinition | None = None,
) -> InvoiceData:
    """Fill missing parse fields from OCR/DI/layout/regex after LLM extract."""
    from app.services.extraction.extraction_orchestrator import merge_extraction_sources

    return merge_extraction_sources(parsed, ocr, dt_definition=dt_definition)


def ensure_extraction_baseline(
    invoice: Invoice,
    parsed: InvoiceData,
    *,
    ocr: OcrArtifact | None = None,
) -> InvoiceData:
    """Populate infrastructure + permit regex fields before playbook gates."""
    from pathlib import Path

    from app.services.extraction.permit_ocr_extractors import extract_permit_fields_from_text

    text = (ocr.text if ocr else None) or parsed.document_text or invoice.document_text or ""
    text = str(text).strip()

    updates: dict[str, object] = {}
    if text and not (parsed.document_text or "").strip():
        updates["document_text"] = text
    if text and not (invoice.document_text or "").strip():
        invoice.document_text = text[:50000] if len(text) > 50000 else text

    if not (invoice.email_attachment_name or "").strip():
        raw_path = (invoice.raw_file_path or "").strip()
        if raw_path:
            name = Path(raw_path).name.strip()
            if name:
                invoice.email_attachment_name = name

    permit_fields = extract_permit_fields_from_text(text) if text else {}
    merged_custom = merge_extracted_field_maps(
        extracted_fields_from_parsed(parsed),
        extracted_fields_from_invoice(invoice),
        permit_fields,
    )
    if merged_custom:
        updates["extracted_fields"] = merged_custom
        invoice.extracted_fields = merged_custom

    if updates:
        return replace(parsed, **updates)
    return parsed
