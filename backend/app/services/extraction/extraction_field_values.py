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

_BANK_DETAILS_LLM_KEYS: tuple[str, ...] = ("bank_bsb", "bank_account", "bank_name")


def _normalized_keys_from_definition(defn: DocumentTypeDefinition) -> list[str]:
    seen: set[str] = set()
    keys: list[str] = []
    for source in (defn.extraction_fields, defn.required_fields):
        for raw in source or []:
            token = str(raw or "").strip().lower()
            if not token or token in seen:
                continue
            if not is_valid_extraction_field_key(token):
                continue
            seen.add(token)
            keys.append(token)
    return keys


def _shipped_defaults_for_definition(defn: DocumentTypeDefinition) -> list[str]:
    """Shipped matrix defaults for a document type (by template code or DT code)."""
    from app.services.classification.document_type_field_defaults import default_extraction_fields
    from app.services.classification.document_type_field_keys import normalize_extraction_field_keys

    for candidate in (defn.matrix_template_code, defn.code):
        token = (candidate or "").strip().upper()
        if not token:
            continue
        defaults = default_extraction_fields(token)
        if defaults:
            return normalize_extraction_field_keys(defaults)
    return []


def effective_extraction_field_keys_for_dt(
    document_types: Sequence[DocumentTypeDefinition],
    dt_code: str,
) -> list[str]:
    """Configured extraction keys for one document type — never a generic invoice fallback."""
    code = (dt_code or "").strip().upper()
    if not code:
        return []
    for defn in document_types:
        if not defn.enabled:
            continue
        if (defn.code or "").strip().upper() != code:
            continue
        keys = _normalized_keys_from_definition(defn)
        if keys:
            return keys
        return _shipped_defaults_for_definition(defn)
    return []


def effective_extraction_field_keys_union(
    document_types: Sequence[DocumentTypeDefinition],
) -> list[str]:
    """Union of configured extraction keys across enabled document types."""
    seen: set[str] = set()
    keys: list[str] = []
    for defn in document_types:
        if not defn.enabled:
            continue
        code = (defn.code or "").strip().upper()
        if not code:
            continue
        for token in effective_extraction_field_keys_for_dt(document_types, code):
            if token in seen:
                continue
            seen.add(token)
            keys.append(token)
    return keys


def non_canonical_extraction_keys(keys: Sequence[str]) -> list[str]:
    """Custom (non-catalogue) keys from a selected extraction list."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in keys:
        token = str(raw or "").strip().lower()
        if not token or token in seen:
            continue
        if token in CANONICAL_EXTRACTION_FIELD_KEYS:
            continue
        if not is_valid_extraction_field_key(token):
            continue
        seen.add(token)
        out.append(token)
    return out


def expand_extraction_keys_for_llm(keys: Sequence[str]) -> list[str]:
    """Map configured keys to top-level LLM scalar keys (expands bank_details)."""
    expanded: list[str] = []
    seen: set[str] = set()
    for raw in keys:
        token = str(raw or "").strip().lower()
        if not token or not is_valid_extraction_field_key(token):
            continue
        if token == "bank_details":
            for sub in _BANK_DETAILS_LLM_KEYS:
                if sub not in seen:
                    seen.add(sub)
                    expanded.append(sub)
            continue
        if token in seen:
            continue
        seen.add(token)
        expanded.append(token)
    return expanded


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


_FIELD_HINT_PATTERNS: dict[str, str] = {
    "vendor": "Vendor, Supplier, From, Seller, Bill From",
    "abn": "ABN, GST, VAT, Tax ID, Company Reg",
    "invoice_no": "Invoice No, Invoice Number, Inv #, Tax Invoice",
    "invoice_date": "Invoice Date, Date, Tax Invoice Date",
    "due_date": "Due Date, Payment Due",
    "po_reference": "PO, Purchase Order, P.O.",
    "so_reference": "SO, Sales Order, S.O.",
    "cost_centre": "Cost Centre, Cost Center, Department",
    "subtotal": "Subtotal, Net Amount, Amount Ex GST",
    "gst": "GST, VAT, Tax",
    "gst_rate": "GST Rate, Tax Rate, VAT %",
    "total": "Total, Amount Due, Balance Due",
    "currency": "Currency symbol or ISO code (AUD, USD, etc.)",
    "line_items": "Product/service table rows with description and amounts",
    "bank_details": "BSB, Account No, IBAN, SWIFT, Bank Name",
    "bank_bsb": "BSB",
    "bank_account": "Account No, Account Number",
    "bank_name": "Bank Name",
    "document_heading": "Document title (Tax Invoice, Credit Note, etc.)",
    "billing_address": "Bill To, Billing Address",
    "seller_name": "Seller, Supplier, From party name",
    "seller_tax_id": "Seller tax ID / ABN",
    "seller_address": "Seller address",
    "buyer_name": "Buyer, Bill To, Customer name",
    "buyer_tax_id": "Buyer tax ID / ABN",
    "buyer_address": "Buyer, Bill To, Ship To address",
    "attachment_name": "File or attachment name when shown",
    "account_code": "Account Code, GL Code",
    "account_name": "Account Name",
}

_SMART_EXCERPT_HEAD = 8000
_SMART_EXCERPT_TAIL = 4000

# Top-level InvoiceData attributes keyed by extraction field name.
_SCALAR_INVOICE_ATTRS: frozenset[str] = frozenset(
    {
        "vendor",
        "abn",
        "invoice_no",
        "invoice_date",
        "due_date",
        "po_reference",
        "cost_centre",
        "subtotal",
        "gst",
        "gst_rate",
        "total",
        "currency",
        "billing_address",
        "bank_bsb",
        "bank_account",
        "document_heading",
    }
)


def build_smart_ocr_excerpt(
    text: str | None,
    *,
    head: int = _SMART_EXCERPT_HEAD,
    tail: int = _SMART_EXCERPT_TAIL,
) -> str:
    """Head + tail excerpt so footer totals survive long documents."""
    body = (text or "").strip()
    if len(body) <= head + tail:
        return body
    return f"{body[:head]}\n...\n{body[-tail:]}"


def _field_hint_for_key(key: str) -> str:
    token = str(key or "").strip().lower()
    if token in _FIELD_HINT_PATTERNS:
        return _FIELD_HINT_PATTERNS[token]
    label = extraction_field_label(token)
    return f'label "{label}" or similar heading in OCR'


def build_extraction_field_manifest(selected_keys: Sequence[str]) -> list[dict[str, str]]:
    """Per-field checklist for LLM extraction (canonical + custom)."""
    seen: set[str] = set()
    manifest: list[dict[str, str]] = []
    for raw in selected_keys:
        token = str(raw or "").strip().lower()
        if not token or token in seen or not is_valid_extraction_field_key(token):
            continue
        seen.add(token)
        if token == "bank_details":
            for sub in _BANK_DETAILS_LLM_KEYS:
                if sub not in seen:
                    seen.add(sub)
                    manifest.append(
                        {
                            "key": sub,
                            "label": extraction_field_label(sub),
                            "hint": _field_hint_for_key(sub),
                        }
                    )
            continue
        if token in ("attachment_name", "document_text"):
            continue
        manifest.append(
            {
                "key": token,
                "label": extraction_field_label(token),
                "hint": _field_hint_for_key(token),
            }
        )
    return manifest


def extraction_field_manifest_prompt_lines(manifest: list[dict[str, str]]) -> list[str]:
    if not manifest:
        return []
    lines = [
        "",
        "Extraction field manifest (extract ONLY these keys; leave empty/null when absent in OCR):",
    ]
    for row in manifest:
        lines.append(f'- `{row["key"]}` ({row["label"]}) — look for: {row["hint"]}')
    lines.extend(
        [
            "- Put custom (non-canonical) string values in extracted_fields.{key} or as a top-level key.",
            "- field_confidence must include every manifest key; use 0.0 when the field is empty.",
        ]
    )
    return lines


_DI_SCALAR_FIELD_KEYS: tuple[str, ...] = (
    "vendor",
    "abn",
    "invoice_no",
    "invoice_date",
    "due_date",
    "po_reference",
    "subtotal",
    "gst",
    "total",
    "currency",
    "cost_centre",
    "billing_address",
)

_DI_PARTY_FIELD_KEYS: tuple[str, ...] = (
    "seller_name",
    "seller_tax_id",
    "seller_abn",
    "seller_address",
    "buyer_name",
    "buyer_tax_id",
    "buyer_address",
)

_FINANCE_FIELD_DEFS: dict[str, dict[str, str]] = {
    "vendor": {
        "finance_role": "Creditor / supplier issuing the invoice (seller on a purchase invoice)",
        "do_not_use": "CustomerName, Bill To, buyer name",
    },
    "abn": {
        "finance_role": "Supplier tax ID (ABN, GST, VAT of the vendor)",
        "do_not_use": "CustomerTaxId, buyer tax ID, invoice number",
    },
    "invoice_no": {
        "finance_role": "Unique invoice document number",
        "do_not_use": "PO number, order reference, tax ID",
    },
    "invoice_date": {
        "finance_role": "Date the invoice was issued",
        "do_not_use": "Due date, delivery date",
    },
    "due_date": {
        "finance_role": "Payment due date",
        "do_not_use": "Invoice date, issue date",
    },
    "po_reference": {
        "finance_role": "Buyer purchase order number referenced on the invoice",
        "do_not_use": "Invoice number, sales order",
    },
    "so_reference": {
        "finance_role": "Sales order number on AR invoices",
        "do_not_use": "PO number, invoice number",
    },
    "subtotal": {
        "finance_role": "Amount before tax (ex-GST / ex-VAT)",
        "do_not_use": "Total, amount due, GST, line item sum",
    },
    "gst": {
        "finance_role": "Tax amount (GST/VAT total)",
        "do_not_use": "Tax rate %, subtotal, total",
    },
    "total": {
        "finance_role": "Grand total or amount due on the invoice",
        "do_not_use": "Subtotal, tax amount only",
    },
    "currency": {
        "finance_role": "ISO 4217 currency code from the document",
        "do_not_use": "Never default to AUD or any code when absent",
    },
    "cost_centre": {
        "finance_role": "Cost centre or project code",
        "do_not_use": "PO number, account code unless labeled cost centre",
    },
    "billing_address": {
        "finance_role": "Bill-to / buyer address block",
        "do_not_use": "Vendor address, remittance address",
    },
    "gst_rate": {
        "finance_role": "Tax percentage as printed (e.g. 10 for 10%)",
        "do_not_use": "Do not calculate from subtotal and gst",
    },
    "bank_bsb": {
        "finance_role": "Bank BSB / routing code when explicitly labeled",
        "do_not_use": "Phone, invoice number, tax ID",
    },
    "bank_account": {
        "finance_role": "Bank account number when explicitly labeled",
        "do_not_use": "Invoice number, ABN",
    },
    "bank_name": {
        "finance_role": "Bank name when explicitly labeled",
        "do_not_use": "Vendor name",
    },
    "seller_name": {
        "finance_role": "Seller / supplier party name",
        "do_not_use": "Buyer name",
    },
    "buyer_name": {
        "finance_role": "Buyer / bill-to party name",
        "do_not_use": "Vendor / supplier name",
    },
}


def di_scalar_field_keys() -> tuple[str, ...]:
    return _DI_SCALAR_FIELD_KEYS


def di_party_field_keys() -> tuple[str, ...]:
    return _DI_PARTY_FIELD_KEYS


def prebuilt_invoice_scalars_active(payload: dict[str, object] | None) -> bool:
    """True when prebuilt-invoice enrich wrote invoice_fields into the OCR payload."""
    if not payload:
        return False
    return "invoice_fields" in payload


def _di_invoice_fields_raw(payload: dict[str, object] | None) -> dict[str, object]:
    if not payload:
        return {}
    raw = payload.get("invoice_fields")
    return dict(raw) if isinstance(raw, dict) else {}


def _di_scalar_value_populated(key: str, raw_value: object) -> bool:
    if raw_value is None:
        return False
    if key == "currency":
        return bool(str(raw_value).strip())
    if key in ("invoice_date", "due_date", "subtotal", "gst", "total"):
        token = str(raw_value).strip()
        return bool(token)
    return bool(str(raw_value).strip())


def di_scalar_fields_populated(payload: dict[str, object] | None) -> set[str]:
    """Canonical scalar keys where DI invoice_fields has a non-empty value."""
    raw = _di_invoice_fields_raw(payload)
    if not raw:
        return set()
    populated: set[str] = set()
    for key in _DI_SCALAR_FIELD_KEYS:
        if _di_scalar_value_populated(key, raw.get(key)):
            populated.add(key)
    return populated


def field_di_authoritative(payload: dict[str, object] | None, field_key: str) -> bool:
    """True when DI provided a non-empty value for this scalar field."""
    if not prebuilt_invoice_scalars_active(payload):
        return False
    return field_key.strip().lower() in di_scalar_fields_populated(payload)


_SCALAR_INFERRED_PARTY_KEYS: dict[str, tuple[str, ...]] = {
    "vendor": ("seller_name",),
    "abn": ("seller_tax_id", "seller_abn"),
    "billing_address": ("buyer_address",),
}


def di_party_fields_populated(payload: dict[str, object] | None) -> set[str]:
    if not payload:
        return set()
    populated: set[str] = set()
    party_raw = payload.get("di_party_fields")
    if isinstance(party_raw, dict):
        populated.update(
            str(key).strip().lower()
            for key, value in party_raw.items()
            if value and str(value).strip()
        )
    scalar_populated = di_scalar_fields_populated(payload)
    for scalar_key, party_keys in _SCALAR_INFERRED_PARTY_KEYS.items():
        if scalar_key in scalar_populated:
            populated.update(party_keys)
    return populated


def resolve_scalars_from_ocr_payload(
    payload: dict[str, object] | None,
    selected_keys: Sequence[str],
) -> InvoiceData | None:
    """Deserialize DI invoice_fields (optionally filtered to selected party keys)."""
    if not prebuilt_invoice_scalars_active(payload):
        return None
    from app.services.extraction.extraction_orchestrator import invoice_data_from_payload_fields

    raw = payload.get("invoice_fields") if payload else None
    if not isinstance(raw, dict):
        return None
    data = invoice_data_from_payload_fields(raw)
    if data is None:
        return None
    party_raw = payload.get("di_party_fields") if payload else None
    if isinstance(party_raw, dict):
        extracted = dict(data.extracted_fields or {})
        selected = {str(k).strip().lower() for k in selected_keys}
        for party_key, value in party_raw.items():
            token = str(party_key or "").strip().lower()
            if token in selected and value:
                extracted[token] = str(value)
        data = replace(data, extracted_fields=extracted)
    return data


def _scalar_value_for_prompt(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    token = str(value).strip()
    return token or None


def normalize_di_scalars_for_prompt(
    payload: dict[str, object] | None,
    selected_keys: Sequence[str],
) -> dict[str, dict[str, str | None]]:
    """Exact string values + Azure source field for LLM user payload."""
    if not prebuilt_invoice_scalars_active(payload):
        return {}
    from app.services.extraction.extraction_orchestrator import invoice_data_from_payload_fields

    raw_fields = payload.get("invoice_fields")
    if not isinstance(raw_fields, dict):
        return {}
    data = invoice_data_from_payload_fields(raw_fields)
    if data is None:
        return {}
    sources = payload.get("di_scalar_sources")
    if not isinstance(sources, dict):
        sources = {}
    out: dict[str, dict[str, str | None]] = {}
    for key in _DI_SCALAR_FIELD_KEYS:
        if not _field_in_selected_keys(key, selected_keys):
            continue
        value = _scalar_value_for_prompt(getattr(data, key, None))
        source = str(sources.get(key) or "").strip() or None
        out[key] = {"value": value, "di_azure_source": source}
    return out


def normalize_di_party_fields_for_prompt(
    payload: dict[str, object] | None,
    selected_keys: Sequence[str],
) -> dict[str, dict[str, str | None]]:
    if not payload:
        return {}
    party_raw = payload.get("di_party_fields")
    if not isinstance(party_raw, dict):
        party_raw = {}
    sources = payload.get("di_party_sources")
    if not isinstance(sources, dict):
        sources = {}
    selected = {str(k).strip().lower() for k in selected_keys}
    out: dict[str, dict[str, str | None]] = {}
    for key in _DI_PARTY_FIELD_KEYS:
        if key not in selected:
            continue
        value = party_raw.get(key)
        token = str(value).strip() if value else None
        source = str(sources.get(key) or "").strip() or None
        out[key] = {"value": token or None, "di_azure_source": source}
    return out


def build_finance_field_manifest(selected_keys: Sequence[str]) -> list[dict[str, str]]:
    """Per-field finance semantics for LLM extraction prompts."""
    base = build_extraction_field_manifest(selected_keys)
    enriched: list[dict[str, str]] = []
    for row in base:
        key = row["key"]
        defs = _FINANCE_FIELD_DEFS.get(key, {})
        enriched.append(
            {
                **row,
                "finance_role": defs.get("finance_role", row["label"]),
                "do_not_use": defs.get("do_not_use", ""),
            }
        )
    return enriched


def finance_field_manifest_prompt_lines(manifest: list[dict[str, str]]) -> list[str]:
    if not manifest:
        return []
    lines = [
        "",
        "Finance field manifest (AP semantics — extract ONLY these keys; empty when absent):",
    ]
    for row in manifest:
        line = f'- `{row["key"]}` ({row["label"]}) — {row.get("finance_role", row["label"])}'
        if row.get("do_not_use"):
            line += f"; do NOT use: {row['do_not_use']}"
        line += f"; OCR labels: {row.get('hint', '')}"
        lines.append(line)
    return lines


def build_scalar_fields_presentation_prompt(
    *,
    di_active: bool,
    di_populated_keys: set[str] | None = None,
) -> list[str]:
    populated = di_populated_keys or set()
    if di_active:
        lines = [
            "",
            "SCALAR FIELDS — AZURE DI (per-field authoritative):",
            "- ocr.azure_di_scalar_fields is pre-extracted by Azure Document Intelligence.",
            "- When azure_di_scalar_fields[key].value is non-null: copy that value EXACTLY (do not override from OCR).",
            "- When azure_di_scalar_fields[key].value is null: extract that key from OCR using finance_field_manifest.",
            "- Use finance_role to verify the concept for OCR-filled keys.",
            "- NEVER default currency to AUD or any other code.",
            "- NEVER derive subtotal, gst, or total from line items or each other unless that exact value is in OCR.",
            "- NEVER swap vendor ↔ buyer, invoice_no ↔ po_reference, invoice_date ↔ due_date.",
            "- Party fields: copy ocr.azure_di_party_fields when value is non-null; else extract from OCR.",
        ]
        if populated:
            lines.append(
                f"- DI-populated keys (copy only): {', '.join(sorted(populated))}."
            )
        lines.append(
            "- field_confidence: 0.95 when copied from azure_di_scalar_fields; per-field OCR confidence otherwise; 0.0 when empty."
        )
        return lines
    return [
        "",
        "SCALAR FIELDS — OCR / LAYOUT (no Azure DI scalars):",
        "- Extract each finance_field_manifest key using its finance_role and OCR labels.",
        "- Copy the exact printed value under the matching label.",
        "- Respect do_not_use — if a value appears only under a forbidden label, leave empty.",
        "- null / \"\" when not explicitly present — no assumptions or defaults.",
    ]


def apply_di_scalars_authoritative(
    parsed: InvoiceData,
    payload: dict[str, object],
    selected_keys: Sequence[str],
) -> InvoiceData:
    """Overwrite only DI-populated scalar keys with invoice_fields values."""
    di_data = resolve_scalars_from_ocr_payload(payload, selected_keys)
    if di_data is None:
        return parsed
    populated = di_scalar_fields_populated(payload)
    updates: dict[str, object] = {}
    for key in _DI_SCALAR_FIELD_KEYS:
        if key not in populated or not _field_in_selected_keys(key, selected_keys):
            continue
        updates[key] = getattr(di_data, key, None)
    party_populated = di_party_fields_populated(payload)
    if party_populated and di_data.extracted_fields:
        merged_extracted = dict(extracted_fields_from_parsed(parsed))
        selected = {str(k).strip().lower() for k in selected_keys}
        for party_key in _DI_PARTY_FIELD_KEYS:
            if party_key in selected and party_key in party_populated and party_key in di_data.extracted_fields:
                merged_extracted[party_key] = di_data.extracted_fields[party_key]
        updates["extracted_fields"] = merged_extracted
    if not updates:
        return parsed
    return replace(parsed, **updates)


def clear_llm_scalars_for_di_populated_fields(
    parsed: InvoiceData,
    selected_keys: Sequence[str],
    payload: dict[str, object] | None,
) -> InvoiceData:
    """Clear LLM values only for scalar keys DI already populated."""
    populated = di_scalar_fields_populated(payload)
    party_populated = di_party_fields_populated(payload)
    if not populated and not party_populated:
        return parsed
    updates: dict[str, object] = {}
    for key in populated:
        if not _field_in_selected_keys(key, selected_keys):
            continue
        if key == "currency":
            updates[key] = ""
        elif key in ("invoice_date", "due_date", "subtotal", "gst", "total"):
            updates[key] = None
        else:
            updates[key] = None
    selected = {str(k).strip().lower() for k in selected_keys}
    extracted = dict(extracted_fields_from_parsed(parsed))
    for party_key in party_populated:
        if party_key in selected:
            extracted.pop(party_key, None)
    if extracted != extracted_fields_from_parsed(parsed):
        updates["extracted_fields"] = extracted
    if not updates:
        return parsed
    return replace(parsed, **updates)


def clear_llm_scalars_for_di(
    parsed: InvoiceData,
    selected_keys: Sequence[str],
    ocr_payload: dict[str, object] | None = None,
) -> InvoiceData:
    """Clear LLM canonical scalars before DI merge applies authoritative values."""
    return clear_llm_scalars_for_di_populated_fields(parsed, selected_keys, ocr_payload)


def attach_di_metadata_to_payload(payload: dict[str, object], invoice_data: InvoiceData) -> None:
    """Store DI scalar/party sources alongside invoice_fields for LLM + merge."""
    raw_fields = invoice_data.raw_fields or {}
    scalar_sources = raw_fields.get("di_scalar_sources")
    if isinstance(scalar_sources, dict):
        payload["di_scalar_sources"] = dict(scalar_sources)
    party = invoice_data.extracted_fields or {}
    payload["di_party_fields"] = {
        k: v for k, v in party.items() if k in _DI_PARTY_FIELD_KEYS and v
    }
    party_sources: dict[str, str] = {}
    if party.get("seller_name"):
        party_sources["seller_name"] = str(
            (scalar_sources or {}).get("vendor") or "VendorName"
        )
    if party.get("seller_tax_id") or party.get("seller_abn"):
        party_sources["seller_tax_id"] = "VendorTaxId"
    if party.get("seller_address"):
        party_sources["seller_address"] = "VendorAddress"
    if party.get("buyer_name"):
        party_sources["buyer_name"] = "CustomerName"
    if party.get("buyer_tax_id"):
        party_sources["buyer_tax_id"] = "CustomerTaxId"
    if party.get("buyer_address"):
        party_sources["buyer_address"] = str(
            (scalar_sources or {}).get("billing_address") or "CustomerAddress"
        )
    if party_sources:
        payload["di_party_sources"] = party_sources


def filter_invoice_fields_for_keys(
    invoice_fields: dict[str, Any] | None,
    selected_keys: Sequence[str],
) -> dict[str, Any]:
    """Restrict DI invoice_fields hints to keys requested for this document type."""
    if not isinstance(invoice_fields, dict) or not invoice_fields:
        return {}
    allowed = {str(k).strip().lower() for k in selected_keys}
    expanded = set(expand_extraction_keys_for_llm(selected_keys))
    out: dict[str, Any] = {}
    for key, value in invoice_fields.items():
        token = str(key or "").strip().lower()
        if token in allowed or token in expanded:
            out[token] = value
    return out


def _field_in_selected_keys(field_name: str, selected_keys: Sequence[str]) -> bool:
    selected = {str(k).strip().lower() for k in selected_keys}
    token = field_name.strip().lower()
    if token in selected:
        return True
    if token in _BANK_DETAILS_LLM_KEYS and "bank_details" in selected:
        return True
    return False


def filter_parsed_to_requested_keys(
    parsed: InvoiceData,
    selected_keys: Sequence[str],
) -> InvoiceData:
    """Drop scalar and extracted_fields values not configured on the document type."""
    if not selected_keys:
        return parsed
    updates: dict[str, object] = {}
    for attr in _SCALAR_INVOICE_ATTRS:
        if attr in ("invoice_date", "due_date", "subtotal", "gst", "gst_rate", "total"):
            if not _field_in_selected_keys(attr, selected_keys):
                updates[attr] = None
        elif attr == "currency":
            if not _field_in_selected_keys(attr, selected_keys):
                updates[attr] = ""
        elif not _field_in_selected_keys(attr, selected_keys):
            updates[attr] = None
    if not _field_in_selected_keys("line_items", selected_keys):
        updates["line_items"] = []
    allowed_extracted = {str(k).strip().lower() for k in selected_keys}
    extracted = {
        k: v
        for k, v in extracted_fields_from_parsed(parsed).items()
        if k in allowed_extracted
    }
    if extracted != extracted_fields_from_parsed(parsed):
        updates["extracted_fields"] = extracted
    if not updates:
        return parsed
    return replace(parsed, **updates)


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
