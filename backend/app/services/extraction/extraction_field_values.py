"""Read/write extraction field values on invoices and parsed OCR payloads."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, TYPE_CHECKING

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_field_keys import (
    CANONICAL_EXTRACTION_FIELD_KEYS,
    INFRASTRUCTURE_EXTRACTION_FIELD_KEYS,
    is_valid_extraction_field_key,
)
from app.services.invoice.invoice_data import InvoiceData

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.schemas.ocr_artifact import OcrArtifact

_BANK_DETAILS_LLM_KEYS: tuple[str, ...] = ("bank_bsb", "bank_account", "bank_name")

# Top-level InvoiceData / invoice column attributes keyed by extraction field name.
INVOICE_SCALAR_ATTRS: frozenset[str] = frozenset(
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

# Canonical keys persisted in invoice.extracted_fields (not top-level InvoiceData attrs).
EXTRACTED_ONLY_ATTRS: frozenset[str] = frozenset(
    {
        "seller_name",
        "seller_tax_id",
        "seller_address",
        "seller_abn",
        "buyer_name",
        "buyer_tax_id",
        "buyer_address",
        "buyer_abn",
        "so_reference",
        "grn_reference",
        "remittance_reference",
        "statement_reference",
        "statement_period",
        "account_code",
        "account_name",
        "bank_name",
        "bank_details",
    }
)

INFRASTRUCTURE_ATTRS: frozenset[str] = INFRASTRUCTURE_EXTRACTION_FIELD_KEYS | frozenset(
    {"email_subject"}
)

# Party fields the LLM should populate via seller/buyer objects, not bogus top-level keys.
PARTY_FIELD_KEYS: frozenset[str] = frozenset(
    {
        "seller_name",
        "seller_tax_id",
        "seller_address",
        "seller_abn",
        "buyer_name",
        "buyer_tax_id",
        "buyer_address",
        "buyer_abn",
    }
)

# Backward-compatible alias used by filter_parsed_to_requested_keys.
_SCALAR_INVOICE_ATTRS = INVOICE_SCALAR_ATTRS


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


# Commercial header/money keys used when org DT has no extraction_fields configured.
_COMMERCIAL_EXTRACTION_FALLBACK: tuple[str, ...] = (
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
    "billing_address",
    "line_items",
)

_NON_TRANSACTIONAL_PLAYBOOKS = frozenset(
    {
        "supporting",
        "reconciliation",
        "non_actionable",
        "informational",
        "master_data",
        "compliance_route",
    }
)


def _playbook_recommended_extraction_keys(defn: DocumentTypeDefinition) -> list[str]:
    """Playbook/route recommended keys — used as fallback when org list is empty."""
    from app.services.classification.document_type_field_keys import normalize_extraction_field_keys
    from app.services.classification.document_type_playbook_profile_service import (
        effective_playbook_profile,
    )
    from app.services.rule_book.extraction_field_config_audit import (
        RECOMMENDED_FIELDS_BY_PLAYBOOK,
        RECOMMENDED_FIELDS_BY_ROUTE,
    )

    profile = (effective_playbook_profile(defn) or "").strip().lower()
    if profile in _NON_TRANSACTIONAL_PLAYBOOKS:
        return []
    keys: list[str] = []
    seen: set[str] = set()
    for raw in RECOMMENDED_FIELDS_BY_PLAYBOOK.get(profile, ()):
        token = str(raw).strip().lower()
        if token and token not in seen:
            seen.add(token)
            keys.append(token)
    route = (defn.route_target or "").strip()
    for raw in RECOMMENDED_FIELDS_BY_ROUTE.get(route, ()):
        token = str(raw).strip().lower()
        if token and token not in seen:
            seen.add(token)
            keys.append(token)
    if keys and "line_items" not in seen:
        keys.append("line_items")
    return normalize_extraction_field_keys(keys) if keys else []


_TRANSACTIONAL_ROUTES = frozenset(
    {
        "Purchase Management",
        "Sales Management",
        "Expenses Management",
    }
)


def _looks_transactional_document_type(defn: DocumentTypeDefinition) -> bool:
    """True when DT metadata implies commercial field extraction is expected."""
    from app.services.classification.document_type_playbook_profile_service import (
        effective_playbook_profile,
    )
    from app.services.rule_book.extraction_field_config_audit import (
        RECOMMENDED_FIELDS_BY_PLAYBOOK,
    )

    profile = (effective_playbook_profile(defn) or "").strip().lower()
    if profile in _NON_TRANSACTIONAL_PLAYBOOKS:
        return False
    if profile in RECOMMENDED_FIELDS_BY_PLAYBOOK:
        return True
    posting = str(defn.posting or "").strip().casefold()
    if posting in {"yes", "y", "true", "1"}:
        return True
    klass = str(defn.klass or "").strip().casefold()
    if "transactional" in klass and "non" not in klass:
        return True
    route = (defn.route_target or "").strip()
    return route in _TRANSACTIONAL_ROUTES


def configured_extraction_keys(defn: DocumentTypeDefinition) -> list[str]:
    """Resolved extraction keys for one document type (via field contracts)."""
    from app.services.extraction.field_contract_resolver import (
        resolve_extraction_field_contracts_for_dt,
    )
    from app.services.extraction.field_contracts import contracts_to_selected_keys

    contracts = resolve_extraction_field_contracts_for_dt(
        [defn],
        defn.code or "",
        dt_definition=defn,
    )
    return contracts_to_selected_keys(contracts)


def effective_extraction_field_keys_for_dt(
    document_types: Sequence[DocumentTypeDefinition],
    dt_code: str,
) -> list[str]:
    """Configured extraction keys for one document type (contract-backed)."""
    from app.services.extraction.field_contract_resolver import (
        selected_keys_from_contracts_for_dt,
    )

    code = (dt_code or "").strip().upper()
    if not code:
        return []
    return selected_keys_from_contracts_for_dt(document_types, code)


def label_value_backfill_keys(
    selected_keys: Sequence[str],
    *,
    parsed: InvoiceData | None = None,
) -> list[str]:
    """Configured keys eligible for OCR label:value regex backfill."""
    out: list[str] = []
    seen: set[str] = set()
    extracted = extracted_fields_from_parsed(parsed) if parsed is not None else {}
    for raw in selected_keys:
        token = str(raw or "").strip().lower()
        if not token or token in seen or not is_valid_extraction_field_key(token):
            continue
        if token in INFRASTRUCTURE_ATTRS or token == "line_items":
            continue
        if token in INVOICE_SCALAR_ATTRS:
            if parsed is not None:
                current = getattr(parsed, token, None)
                if current is not None and str(current).strip():
                    continue
        elif token in extracted and extracted[token]:
            continue
        seen.add(token)
        out.append(token)
    return out


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
    "currency": "Currency",
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
        hint = row.get("hint") or _field_hint_for_key(row["key"])
        lines.append(f'- key `{row["key"]}` — label "{row["label"]}" — look for: {hint}')
    lines.extend(extraction_accuracy_prompt_lines())
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
    from app.registry.adapter import use_field_registry, get_registry_adapter

    if use_field_registry():
        return get_registry_adapter().hint_for(key)
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
    lines.extend(extraction_accuracy_prompt_lines())
    lines.extend(
        [
            "- Put custom (non-canonical) string values in extracted_fields.{key} or as a top-level key.",
        ]
    )
    return lines


def extraction_accuracy_prompt_lines() -> list[str]:
    """Shared conservative OCR-only rules for primary extract and gap-fill prompts."""
    from app.registry.adapter import use_field_registry, get_registry_adapter

    if use_field_registry():
        return get_registry_adapter().accuracy_prompt_lines()
    return [
        "",
        "Accuracy rules (mandatory):",
        "- Copy values verbatim from OCR only; empty is correct when a field is absent — never invent to satisfy the manifest.",
        "- If a value is not explicitly printed in ocr.text_excerpt or field_snippets, leave the field empty.",
        "- Never default currency (e.g. AUD), assume tax rates, or calculate totals from other fields.",
        "- Never swap semantically similar fields (invoice_no ≠ po_reference, vendor ≠ buyer).",
        "- invoice_no: copy ONLY the invoice/reference token — never include trailing DATED/DATE labels or dates in invoice_no; put dates in invoice_date.",
        "- field_confidence: 0.0 when empty; 0.95+ only for verbatim OCR copies.",
        "- Example: if you see 'Tax Invoice' but no invoice number label, invoice_no stays empty.",
        "- Example: if project_code is not labeled in OCR, do not infer it from PO or line items.",
    ]


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

_GLOBAL_DEPRIORITIZED_LABEL_QUALIFIERS: tuple[str, ...] = (
    "proforma",
    "pro-forma",
    "draft",
    "quotation",
    "estimate",
)

_FIELD_DEPRIORITIZED_LABELS: dict[str, tuple[str, ...]] = {
    "invoice_no": _GLOBAL_DEPRIORITIZED_LABEL_QUALIFIERS,
    "po_reference": _GLOBAL_DEPRIORITIZED_LABEL_QUALIFIERS,
    "so_reference": _GLOBAL_DEPRIORITIZED_LABEL_QUALIFIERS,
}

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
    """True when prebuilt-invoice enrich wrote non-empty invoice_fields into the OCR payload."""
    if not payload:
        return False
    if "invoice_fields" not in payload:
        return False
    return bool(di_scalar_fields_populated(payload))


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


def field_di_authoritative(
    payload: dict[str, object] | None,
    field_key: str,
    *,
    ocr_text: str | None = None,
    selected_keys: Sequence[str] | None = None,
) -> bool:
    """True when DI provided a non-empty value that is OCR-grounded (trusted)."""
    if not prebuilt_invoice_scalars_active(payload):
        return False
    if not ocr_text:
        return False
    token = field_key.strip().lower()
    keys = (
        list(selected_keys)
        if selected_keys
        else list(_DI_SCALAR_FIELD_KEYS) + list(_DI_PARTY_FIELD_KEYS)
    )
    if token in di_trusted_scalar_fields(payload, ocr_text, keys):
        return True
    return token in di_trusted_party_fields(payload, ocr_text, keys)


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


def di_trusted_scalar_fields(
    payload: dict[str, object] | None,
    ocr_text: str | None,
    selected_keys: Sequence[str],
) -> set[str]:
    """DI-populated scalar keys that are OCR-grounded and pass DI confidence when present."""
    populated = di_scalar_fields_populated(payload)
    if not populated or not ocr_text:
        return set()
    di_data = resolve_scalars_from_ocr_payload(payload, selected_keys)
    if di_data is None:
        return set()
    conf_map: dict[str, object] = {}
    if payload and isinstance(payload.get("field_confidence"), dict):
        conf_map = dict(payload["field_confidence"])  # type: ignore[arg-type]
    from app.config import get_settings

    di_floor = get_settings().di_field_trust_min_confidence
    trusted: set[str] = set()
    for key in populated:
        if not _field_in_selected_keys(key, selected_keys):
            continue
        value = getattr(di_data, key, None)
        if not _scalar_grounded_for_gap_fill(key, value, ocr_text, context=di_data):
            continue
        conf_raw = conf_map.get(key)
        if conf_raw is not None:
            try:
                if float(conf_raw) < di_floor:
                    continue
            except (TypeError, ValueError):
                pass
        trusted.add(key)
    return trusted


def di_trusted_party_fields(
    payload: dict[str, object] | None,
    ocr_text: str | None,
    selected_keys: Sequence[str],
) -> set[str]:
    """DI party keys with explicit values that are OCR-grounded."""
    if not payload or not ocr_text:
        return set()
    populated = di_party_fields_populated(payload)
    if not populated:
        return set()
    selected = {str(k).strip().lower() for k in selected_keys}
    party_raw = payload.get("di_party_fields")
    if not isinstance(party_raw, dict):
        party_raw = {}
    trusted: set[str] = set()
    for party_key in populated:
        if party_key not in selected:
            continue
        value = party_raw.get(party_key)
        if not value or not str(value).strip():
            continue
        if _scalar_grounded_for_gap_fill(party_key, str(value).strip(), ocr_text):
            trusted.add(party_key)
    return trusted


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
    from app.registry.adapter import use_field_registry, get_registry_adapter

    base = build_extraction_field_manifest(selected_keys)
    if use_field_registry():
        defs_by_key = {
            row["key"]: row for row in get_registry_adapter().finance_defs_for_keys(list(selected_keys))
        }
        enriched: list[dict[str, str]] = []
        for row in base:
            defs = defs_by_key.get(row["key"], {})
            enriched.append(
                {
                    **row,
                    "finance_role": defs.get("finance_role", row["label"]),
                    "do_not_use": defs.get("do_not_use", ""),
                    "deprioritized_labels": defs.get("deprioritized_labels", []),
                }
            )
        return enriched
    enriched = []
    for row in base:
        key = row["key"]
        defs = _FINANCE_FIELD_DEFS.get(key, {})
        deprioritized = _FIELD_DEPRIORITIZED_LABELS.get(key, ())
        enriched.append(
            {
                **row,
                "finance_role": defs.get("finance_role", row["label"]),
                "do_not_use": defs.get("do_not_use", ""),
                "deprioritized_labels": list(deprioritized),
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
        deprioritized = row.get("deprioritized_labels") or []
        if deprioritized:
            line += f"; deprioritize labels containing: {', '.join(deprioritized)}"
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
                f"- DI-trusted keys (copy only): {', '.join(sorted(populated))}."
            )
        lines.append(
            "- DI hints not in the trusted list must be verified against OCR; do not copy if not visible in text."
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
    *,
    ocr_text: str | None = None,
) -> InvoiceData:
    """Overwrite only OCR-grounded (trusted) DI scalar keys with invoice_fields values."""
    di_data = resolve_scalars_from_ocr_payload(payload, selected_keys)
    if di_data is None:
        return parsed
    trusted = di_trusted_scalar_fields(payload, ocr_text, selected_keys)
    updates: dict[str, object] = {}
    for key in _DI_SCALAR_FIELD_KEYS:
        if key not in trusted or not _field_in_selected_keys(key, selected_keys):
            continue
        updates[key] = getattr(di_data, key, None)
    party_trusted = di_trusted_party_fields(payload, ocr_text, selected_keys)
    if party_trusted and di_data.extracted_fields:
        merged_extracted = dict(extracted_fields_from_parsed(parsed))
        selected = {str(k).strip().lower() for k in selected_keys}
        for party_key in _DI_PARTY_FIELD_KEYS:
            if (
                party_key in selected
                and party_key in party_trusted
                and party_key in di_data.extracted_fields
            ):
                merged_extracted[party_key] = di_data.extracted_fields[party_key]
        updates["extracted_fields"] = merged_extracted
    if not updates:
        return parsed
    return replace(parsed, **updates)


def _scalar_value_for_extracted_field(key: str, value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    token = str(value).strip()
    return token or None


def merge_extracted_fields_with_authority(
    *,
    base: dict[str, str],
    llm_extracted: dict[str, str] | None,
    payload: dict[str, object] | None,
    selected_keys: Sequence[str],
    ocr_text: str | None,
) -> dict[str, str]:
    """Merge extracted_fields giving DI-trusted scalars authority over LLM guesses."""
    merged = dict(base)
    llm_map = llm_extracted or {}
    keys = list(selected_keys or ())
    for key, value in llm_map.items():
        token = str(key or "").strip().lower()
        if not token or not str(value or "").strip():
            continue
        if field_di_authoritative(payload, token, ocr_text=ocr_text, selected_keys=keys):
            continue
        merged[token] = str(value).strip()

    di_data = resolve_scalars_from_ocr_payload(payload, keys)
    if di_data is None:
        return merged
    trusted = di_trusted_scalar_fields(payload, ocr_text, keys)
    for key in trusted:
        if key not in INVOICE_SCALAR_ATTRS:
            continue
        scalar_val = _scalar_value_for_extracted_field(key, getattr(di_data, key, None))
        if scalar_val:
            merged[key] = scalar_val
        else:
            merged.pop(key, None)
    return merged


def sync_extracted_fields_with_di_authority(
    parsed: InvoiceData,
    payload: dict[str, object] | None,
    selected_keys: Sequence[str],
    *,
    ocr_text: str | None = None,
) -> InvoiceData:
    """Align extracted_fields with DI-trusted scalar columns on parsed."""
    trusted = di_trusted_scalar_fields(payload, ocr_text, selected_keys)
    if not trusted:
        return parsed
    extracted = dict(extracted_fields_from_parsed(parsed))
    for key in trusted:
        if key not in INVOICE_SCALAR_ATTRS:
            continue
        scalar_val = _scalar_value_for_extracted_field(key, getattr(parsed, key, None))
        if scalar_val:
            extracted[key] = scalar_val
        else:
            extracted.pop(key, None)
    return replace(parsed, extracted_fields=extracted)


def clear_llm_scalars_for_di_populated_fields(
    parsed: InvoiceData,
    selected_keys: Sequence[str],
    payload: dict[str, object] | None,
    *,
    ocr_text: str | None = None,
) -> InvoiceData:
    """Clear LLM values only for scalar keys where DI values are OCR-grounded (trusted)."""
    populated = di_trusted_scalar_fields(payload, ocr_text, selected_keys)
    party_populated = di_trusted_party_fields(payload, ocr_text, selected_keys)
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
    *,
    ocr_text: str | None = None,
) -> InvoiceData:
    """Clear LLM canonical scalars before DI merge applies authoritative values."""
    return clear_llm_scalars_for_di_populated_fields(
        parsed, selected_keys, ocr_payload, ocr_text=ocr_text
    )


def attach_di_metadata_to_payload(payload: dict[str, object], invoice_data: InvoiceData) -> None:
    """Store DI scalar/party sources alongside invoice_fields for LLM + merge."""
    attach_extraction_metadata_to_payload(payload, invoice_data)


def attach_extraction_metadata_to_payload(
    payload: dict[str, object],
    invoice_data: InvoiceData,
    *,
    decision: Any = None,
    strategy_name: str | None = None,
    models_run: list[str] | None = None,
    layout_line_mode: str | None = None,
) -> None:
    """Store DI scalar/party sources + route/confidence metadata on OCR payload."""
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

    field_confidence = raw_fields.get("field_confidence")
    if isinstance(field_confidence, dict):
        payload["field_confidence"] = dict(field_confidence)
    field_sources = raw_fields.get("field_sources")
    if isinstance(field_sources, dict):
        payload["field_sources"] = dict(field_sources)
    line_conf = raw_fields.get("di_line_item_confidences")
    if isinstance(line_conf, list):
        payload["di_line_item_confidences"] = list(line_conf)

    if decision is not None:
        payload["extraction_route"] = getattr(
            getattr(decision, "route", None), "value", None
        ) or str(getattr(decision, "route", ""))
        payload["route_reasons"] = list(getattr(decision, "reasons", ()) or ())
        hints = list(getattr(decision, "review_hints", ()) or ())
        if hints:
            payload["review_hints"] = hints
    if strategy_name:
        payload["extraction_strategy"] = strategy_name
    if models_run is not None:
        payload["di_models_run"] = list(models_run)
    if layout_line_mode:
        payload["layout_line_mode"] = layout_line_mode


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
    selected = {str(k).strip().lower() for k in selected_keys if str(k or "").strip()}
    if not selected:
        return True
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


def _sanitize_extracted_field_value(key: str, value: object) -> str | None:
    from app.services.purchase.po_reference import is_plausible_po_reference
    from app.services.sales.so_reference import is_plausible_so_reference
    from app.services.shared.reference_field_sanitizer import (
        is_reference_like_extraction_key,
        sanitize_reference_for_column,
        sanitize_reference_value,
    )

    text = str(value or "").strip()
    if not text:
        return None
    if not is_reference_like_extraction_key(key):
        return text
    if key in {"so_reference", "sales_order", "sales_order_no", "so_number"}:
        return sanitize_reference_for_column(text, max_len=100, is_plausible=is_plausible_so_reference)
    if key in {"po_reference", "purchase_order", "purchase_order_no", "po_number"}:
        return sanitize_reference_for_column(text, max_len=100, is_plausible=is_plausible_po_reference)
    return sanitize_reference_value(text, max_len=100)


def normalize_extracted_fields_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        token = str(key or "").strip().lower()
        if not token or not is_valid_extraction_field_key(token):
            continue
        text = _sanitize_extracted_field_value(token, value)
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
    from app.services.purchase.po_reference import ensure_invoice_po_reference
    from app.services.sales.so_reference import ensure_invoice_so_reference

    ensure_invoice_so_reference(invoice)
    ensure_invoice_po_reference(invoice)


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


def harvest_configured_fields_from_llm_raw(
    raw: dict[str, Any] | None,
    *,
    selected_keys: Sequence[str],
) -> dict[str, str]:
    """Harvest configured extraction keys from LLM JSON into extracted_fields."""
    if not isinstance(raw, dict) or not selected_keys:
        return {}
    nested = raw.get("extracted_fields")
    nested_map = normalize_extracted_fields_map(nested) if isinstance(nested, dict) else {}
    out: dict[str, str] = dict(nested_map)
    selected = {str(k).strip().lower() for k in selected_keys if str(k or "").strip()}

    for token in selected:
        if not token or not is_valid_extraction_field_key(token):
            continue
        if token in INFRASTRUCTURE_ATTRS or token == "line_items":
            continue
        if token in out:
            continue
        if token in PARTY_FIELD_KEYS:
            continue
        if token in INVOICE_SCALAR_ATTRS:
            continue
        value: str | None = None
        if isinstance(nested, dict) and nested.get(token) not in (None, "", {}):
            value = str(nested.get(token)).strip()
        elif token in raw and raw[token] not in (None, "", {}):
            candidate = raw[token]
            if not isinstance(candidate, (dict, list)):
                value = str(candidate).strip()
        if value:
            out[token] = value
    return {k: v for k, v in out.items() if k in selected}


def harvest_custom_fields_from_llm_raw(
    raw: dict[str, Any] | None,
    *,
    custom_keys: Sequence[str] | None = None,
    selected_keys: Sequence[str] | None = None,
) -> dict[str, str]:
    """Collect user-defined field values from LLM JSON (nested or top-level)."""
    if not isinstance(raw, dict):
        return {}
    configured = harvest_configured_fields_from_llm_raw(raw, selected_keys=selected_keys or ())
    extracted = normalize_extracted_fields_map(raw.get("extracted_fields"))
    extracted = merge_extracted_field_maps(extracted, configured)
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
    selected = {str(k).strip().lower() for k in (selected_keys or ())}
    for key, value in raw.items():
        token = str(key or "").strip().lower()
        if not token or token in _LLM_RESERVED_RAW_KEYS:
            continue
        if token in CANONICAL_EXTRACTION_FIELD_KEYS:
            if not selected or token not in selected:
                continue
            if token in INVOICE_SCALAR_ATTRS or token in PARTY_FIELD_KEYS:
                continue
        if not is_valid_extraction_field_key(token) or token in extracted:
            continue
        text = str(value or "").strip()
        if text:
            extracted[token] = text
    if selected:
        extracted = {k: v for k, v in extracted.items() if k in selected}
    return extracted


def _scalar_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def extraction_field_present_on_parsed(key: str, parsed: InvoiceData) -> bool:
    """True when a configured extraction key has a non-empty value on parsed data."""
    token = key.strip().lower()
    if not token:
        return False
    if token == "line_items":
        return bool(parsed.line_items)
    if token in INVOICE_SCALAR_ATTRS:
        val = getattr(parsed, token, None)
        if token == "currency":
            return bool(str(val or "").strip())
        if token in ("invoice_date", "due_date", "subtotal", "gst", "gst_rate", "total"):
            return val is not None
        return val is not None and str(val).strip()
    if token == "bank_details":
        return bool((parsed.bank_bsb or "").strip() or (parsed.bank_account or "").strip())
    custom = extracted_fields_from_parsed(parsed)
    return bool(custom.get(token))


def extraction_field_present(
    key: str,
    *,
    parsed: InvoiceData,
    invoice: Invoice | None = None,
) -> bool:
    """Presence check using invoice+parsed when available, else parsed only."""
    if invoice is not None:
        from app.services.classification.document_type_field_checks import field_is_present
        from app.services.classification.document_type_rule_engine import build_document_classifier_context

        ctx = build_document_classifier_context(invoice=invoice, parsed=parsed)
        return field_is_present(key, invoice=invoice, parsed=parsed, ctx=ctx)
    return extraction_field_present_on_parsed(key, parsed)


def missing_configured_extraction_keys(
    selected_keys: Sequence[str],
    *,
    parsed: InvoiceData,
    invoice: Invoice | None = None,
    ocr_text: str | None = None,
    ocr_payload: dict[str, object] | None = None,
) -> list[str]:
    """Configured extraction keys still empty after main extract + OCR enrich."""
    missing: list[str] = []
    for raw in selected_keys:
        token = str(raw or "").strip().lower()
        if not token or not is_valid_extraction_field_key(token):
            continue
        if token in INFRASTRUCTURE_ATTRS:
            continue
        if token == "line_items":
            if extraction_field_present_on_parsed(token, parsed):
                continue
            from app.services.extraction.line_items_parser import (
                document_has_charge_lines,
                document_has_line_item_table,
            )

            if document_has_line_item_table(ocr_text, ocr_payload) or document_has_charge_lines(
                ocr_text
            ):
                missing.append(token)
            continue
        if not extraction_field_present(token, parsed=parsed, invoice=invoice):
            missing.append(token)
    return missing


_SNIPPET_CONTEXT_LINES = 4


def build_field_ocr_snippets(text: str | None, keys: Sequence[str]) -> dict[str, str]:
    """Per-field OCR context windows for gap-fill prompts."""
    body = (text or "").strip()
    if not body or not keys:
        return {}
    lines = body.splitlines()
    fallback = build_smart_ocr_excerpt(body)[:2000]
    out: dict[str, str] = {}
    for raw_key in keys:
        token = str(raw_key or "").strip().lower()
        if not token or token in out:
            continue
        from app.services.extraction.finance_field_labels import MONEY_SCALAR_KEYS

        if token in MONEY_SCALAR_KEYS:
            tail = body[-1500:] if len(body) > 1500 else body
            label = extraction_field_label(token)
            hint = _FIELD_HINT_PATTERNS.get(token, label)
            search_terms = [label, token.replace("_", " ")]
            if hint and hint not in search_terms:
                search_terms.append(hint)
            snippet_lines: list[str] = []
            for index, line in enumerate(lines):
                line_lower = line.lower()
                if any(term.lower() in line_lower for term in search_terms if term):
                    start = max(0, index - _SNIPPET_CONTEXT_LINES)
                    end = min(len(lines), index + _SNIPPET_CONTEXT_LINES + 1)
                    snippet_lines = lines[start:end]
                    break
            if snippet_lines:
                out[token] = "\n".join(snippet_lines).strip()
            else:
                out[token] = tail.strip() or fallback
            continue
        label = extraction_field_label(token)
        hint = _FIELD_HINT_PATTERNS.get(token, label)
        search_terms = [label, token.replace("_", " ")]
        if hint and hint not in search_terms:
            search_terms.append(hint)
        snippet_lines: list[str] = []
        for index, line in enumerate(lines):
            line_lower = line.lower()
            if any(term.lower() in line_lower for term in search_terms if term):
                start = max(0, index - _SNIPPET_CONTEXT_LINES)
                end = min(len(lines), index + _SNIPPET_CONTEXT_LINES + 1)
                snippet_lines = lines[start:end]
                break
        if not snippet_lines and token in _FIELD_HINT_PATTERNS:
            for part in re.split(r",\s*", _FIELD_HINT_PATTERNS[token]):
                part = part.strip()
                if not part:
                    continue
                for index, line in enumerate(lines):
                    if part.lower() in line.lower():
                        start = max(0, index - _SNIPPET_CONTEXT_LINES)
                        end = min(len(lines), index + _SNIPPET_CONTEXT_LINES + 1)
                        snippet_lines = lines[start:end]
                        break
                if snippet_lines:
                    break
        out[token] = "\n".join(snippet_lines).strip() if snippet_lines else fallback
    return out


def gap_fill_field_descriptors(keys: Sequence[str]) -> list[dict[str, str]]:
    """Per-field label/hint rows for gap-fill prompts."""
    return build_extraction_field_manifest(keys)


@dataclass(frozen=True)
class GapFillMergeResult:
    parsed: InvoiceData
    filled: tuple[str, ...]
    rejected: tuple[str, ...]


def _scalar_grounded_for_gap_fill(
    key: str,
    value: object,
    ocr_text: str | None,
    *,
    context: InvoiceData | None = None,
) -> bool:
    from datetime import date
    from decimal import Decimal

    from app.services.extraction.field_grounding_service import (
        _date_grounded_in_ocr,
        _invoice_no_grounded,
        _money_grounded_in_ocr,
        currency_passes_grounding,
        value_grounded_in_ocr,
    )

    if _scalar_empty(value):
        return False
    if key == "invoice_no":
        return _invoice_no_grounded(str(value), ocr_text)
    if key in ("invoice_date", "due_date"):
        if isinstance(value, date):
            return _date_grounded_in_ocr(value, ocr_text)
        return False
    if key in ("subtotal", "gst", "gst_rate", "total"):
        amount = value if isinstance(value, Decimal) else value
        return _money_grounded_in_ocr(amount, ocr_text, field_key=key)
    if key == "currency":
        from dataclasses import replace

        base = context if context is not None else InvoiceData()
        probe = replace(base, currency=str(value).strip().upper())
        return currency_passes_grounding(probe, ocr_text)
    return value_grounded_in_ocr(str(value), ocr_text)


def merge_gap_fill_into_parsed(
    parsed: InvoiceData,
    gap: InvoiceData,
    *,
    missing_keys: Sequence[str],
    ocr_text: str | None,
    ocr_payload: dict[str, object] | None = None,
) -> GapFillMergeResult:
    """Merge gap-fill values into empty fields only; reject ungrounded values."""
    from app.services.extraction.field_grounding_service import ground_extracted_fields_map

    missing = [str(k).strip().lower() for k in missing_keys if str(k or "").strip()]
    if not missing:
        return GapFillMergeResult(parsed=parsed, filled=(), rejected=())

    filled: list[str] = []
    rejected: list[str] = []
    updates: dict[str, object] = {}
    extracted = dict(extracted_fields_from_parsed(parsed))
    gap_extracted = dict(extracted_fields_from_parsed(gap))

    for key in missing:
        if extraction_field_present_on_parsed(key, parsed):
            continue
        if key in INVOICE_SCALAR_ATTRS:
            candidate = getattr(gap, key, None)
            if _scalar_empty(candidate):
                continue
            if not _scalar_grounded_for_gap_fill(key, candidate, ocr_text, context=parsed):
                rejected.append(key)
                continue
            updates[key] = candidate
            filled.append(key)
            continue
        if key == "line_items":
            candidate_items = list(gap.line_items or [])
            from app.services.extraction.line_items_parser import document_has_line_item_table

            if not candidate_items:
                if document_has_line_item_table(ocr_text, ocr_payload):
                    rejected.append(key)
                continue
            from app.services.extraction.line_items_parser import document_has_qty_only_table
            from app.services.extraction.line_items_sanitizer import sanitize_line_items

            payload_dict = ocr_payload or {}
            sanitized = sanitize_line_items(
                candidate_items,
                extracted_fields=gap.extracted_fields,
                vendor=gap.vendor or parsed.vendor,
                invoice_no=gap.invoice_no or parsed.invoice_no,
                po_reference=gap.po_reference or parsed.po_reference,
                so_reference=(gap.extracted_fields or {}).get("so_reference")
                or (parsed.extracted_fields or {}).get("so_reference"),
                cost_centre=gap.cost_centre or parsed.cost_centre,
                allow_qty_only=document_has_qty_only_table(ocr_text, payload_dict),
            )
            if not sanitized:
                rejected.append(key)
                continue
            updates["line_items"] = sanitized
            filled.append(key)
            continue
        if key in PARTY_FIELD_KEYS or key in EXTRACTED_ONLY_ATTRS or key not in CANONICAL_EXTRACTION_FIELD_KEYS:
            candidate = gap_extracted.get(key)
            if not candidate:
                continue
            grounded = ground_extracted_fields_map(
                {key: candidate},
                ocr_text,
                requested_keys=[key],
            )
            if not grounded.get(key):
                rejected.append(key)
                continue
            extracted[key] = grounded[key]
            filled.append(key)

    if extracted != extracted_fields_from_parsed(parsed):
        updates["extracted_fields"] = extracted
    if not updates:
        return GapFillMergeResult(parsed=parsed, filled=tuple(filled), rejected=tuple(rejected))
    return GapFillMergeResult(
        parsed=replace(parsed, **updates),
        filled=tuple(filled),
        rejected=tuple(rejected),
    )


def enrich_parsed_from_ocr(
    parsed: InvoiceData,
    ocr: OcrArtifact,
    *,
    dt_definition: DocumentTypeDefinition | None = None,
    trace: object | None = None,
) -> InvoiceData:
    """Fill missing parse fields from OCR/DI/layout/regex after LLM extract."""
    from app.services.extraction.extraction_orchestrator import merge_extraction_sources

    return merge_extraction_sources(parsed, ocr, dt_definition=dt_definition, trace=trace)


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
