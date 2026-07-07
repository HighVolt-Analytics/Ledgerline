"""Unified merge of LLM, DI, layout KV, and regex extraction sources."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, TYPE_CHECKING

from app.schemas.document_type import DocumentTypeDefinition
from app.services.extraction.custom_field_ocr_extractors import extract_custom_fields_from_text
from app.services.extraction.extraction_field_values import (
    effective_extraction_field_keys_for_dt,
    extracted_fields_from_parsed,
    harvest_custom_fields_from_llm_raw,
    merge_extracted_field_maps,
    non_canonical_extraction_keys,
)
from app.services.extraction.layout_field_extractor import extract_key_value_fields
from app.services.extraction.pdf_parser import (
    _merge_prefer_complete,
    parse_local_text,
    post_process_parsed_data,
)
from app.services.extraction.permit_ocr_extractors import extract_permit_fields_from_text
from app.services.extraction.line_items_parser import (
    deserialize_line_items,
    enrich_line_items_from_text,
    line_items_from_ocr_payload,
    merge_line_item_lists,
    serialize_line_items,
)
from app.services.extraction.line_item_skip_patterns import has_trusted_line_items
from app.services.extraction.line_items_sanitizer import sanitize_line_items
from app.services.extraction.field_grounding_service import (
    ground_invoice_scalars,
    merge_bank_fields,
)
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.services.master_data.vendor_name_utils import normalize_vendor_name
from app.services.shared.flexible_date import parse_flexible_date
from app.utils.abn_validator import storage_abn

if TYPE_CHECKING:
    from app.schemas.ocr_artifact import OcrArtifact


_SCALAR_FILL_FIELDS = (
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
    "bank_bsb",
    "bank_account",
    "cost_centre",
    "document_heading",
)

_NON_INVOICE_DI_PROFILES = frozenset(
    {
        "supporting",
        "reconciliation",
    }
)


def should_run_prebuilt_invoice_di(
    confirmed_dt: str,
    dt_definition: DocumentTypeDefinition | None,
) -> bool:
    if dt_definition is None:
        return True
    profile = (dt_definition.playbook_profile or "").strip().lower()
    if profile in _NON_INVOICE_DI_PROFILES:
        return False
    purchase_role = (dt_definition.purchase_bundle_role or "").strip().lower()
    sales_role = (dt_definition.sales_bundle_role or "").strip().lower()
    if purchase_role in {"po", "grn"} or sales_role in {"so", "dn"}:
        return False
    if profile == "supporting":
        return False
    return True


def _scalar_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def invoice_data_to_payload_fields(data: InvoiceData) -> dict[str, Any]:
    return {
        "vendor": data.vendor,
        "abn": data.abn,
        "invoice_no": data.invoice_no,
        "invoice_date": data.invoice_date.isoformat() if data.invoice_date else None,
        "due_date": data.due_date.isoformat() if data.due_date else None,
        "po_reference": data.po_reference,
        "subtotal": str(data.subtotal) if data.subtotal is not None else None,
        "gst": str(data.gst) if data.gst is not None else None,
        "total": str(data.total) if data.total is not None else None,
        "currency": data.currency,
        "cost_centre": data.cost_centre,
        "billing_address": data.billing_address,
        "line_items": serialize_line_items(data.line_items),
        "line_items_count": len(data.line_items),
    }


def invoice_data_from_payload_fields(raw: dict[str, Any] | None) -> InvoiceData | None:
    if not raw:
        return None
    invoice_date = raw.get("invoice_date")
    due_date = raw.get("due_date")
    if isinstance(invoice_date, date):
        inv_date = invoice_date
    else:
        inv_date = parse_flexible_date(str(invoice_date) if invoice_date else None)
    if isinstance(due_date, date):
        due = due_date
    else:
        due = parse_flexible_date(str(due_date) if due_date else None)

    return InvoiceData(
        vendor=(raw.get("vendor") or None),
        abn=storage_abn(str(raw.get("abn") or "").strip() or None),
        invoice_no=(str(raw.get("invoice_no")).strip() if raw.get("invoice_no") else None),
        invoice_date=inv_date,
        due_date=due,
        po_reference=(str(raw.get("po_reference")).strip() if raw.get("po_reference") else None),
        subtotal=_parse_decimal(raw.get("subtotal")),
        gst=_parse_decimal(raw.get("gst")),
        total=_parse_decimal(raw.get("total")),
        currency=(str(raw.get("currency") or "AUD").strip().upper() or "AUD"),
        cost_centre=(str(raw.get("cost_centre")).strip() if raw.get("cost_centre") else None),
        billing_address=(str(raw.get("billing_address")).strip() if raw.get("billing_address") else None),
        line_items=deserialize_line_items(raw.get("line_items")),
        raw_fields={"source": "di_payload"},
    )


_DI_MERGE_KEYS: frozenset[str] = frozenset(
    {
        "vendor",
        "abn",
        "invoice_no",
        "invoice_date",
        "due_date",
        "po_reference",
        "subtotal",
        "gst",
        "gst_rate",
        "total",
        "cost_centre",
        "billing_address",
        "line_items",
        "bank_details",
        "document_heading",
    }
)


def _configured_key_set(
    dt_definition: DocumentTypeDefinition | None,
) -> set[str]:
    if dt_definition is None:
        return set()
    return set(
        effective_extraction_field_keys_for_dt([dt_definition], dt_definition.code)
    )


def _field_configured(field_name: str, configured: set[str]) -> bool:
    if not configured:
        return True
    if field_name in configured:
        return True
    if field_name in ("bank_bsb", "bank_account", "bank_name") and "bank_details" in configured:
        return True
    return False


def _apply_layout_kv(
    data: InvoiceData,
    kv: dict[str, str],
    *,
    configured: set[str],
) -> InvoiceData:
    if not kv:
        return data
    updates: dict[str, object] = {}
    if _field_configured("vendor", configured) and kv.get("vendor") and _scalar_empty(data.vendor):
        updates["vendor"] = normalize_vendor_name(kv["vendor"]) or kv["vendor"]
    if _field_configured("abn", configured) and kv.get("abn") and _scalar_empty(data.abn):
        updates["abn"] = storage_abn(kv["abn"])
    if _field_configured("invoice_no", configured) and kv.get("invoice_no") and _scalar_empty(data.invoice_no):
        updates["invoice_no"] = kv["invoice_no"].strip()
    if _field_configured("po_reference", configured) and kv.get("po_reference") and _scalar_empty(data.po_reference):
        updates["po_reference"] = kv["po_reference"].strip()
    if _field_configured("invoice_date", configured) and kv.get("invoice_date") and data.invoice_date is None:
        parsed = parse_flexible_date(kv["invoice_date"])
        if parsed:
            updates["invoice_date"] = parsed
    if _field_configured("due_date", configured) and kv.get("due_date") and data.due_date is None:
        parsed = parse_flexible_date(kv["due_date"])
        if parsed:
            updates["due_date"] = parsed
    for money_key in ("subtotal", "gst", "gst_rate", "total"):
        if not _field_configured(money_key, configured):
            continue
        if kv.get(money_key) and getattr(data, money_key) is None:
            if money_key == "gst_rate":
                from app.services.extraction.gst_rate import parse_gst_rate_percent

                parsed_rate = parse_gst_rate_percent(kv[money_key])
                if parsed_rate is not None:
                    updates[money_key] = parsed_rate
            else:
                amount = _parse_decimal(kv[money_key])
                if amount is not None:
                    updates[money_key] = amount

    raw_fields = dict(data.raw_fields or {})
    raw_fields["layout_kv"] = kv
    updates["raw_fields"] = raw_fields
    if updates:
        return replace(data, **updates)
    return data


def _apply_absent_fields(
    data: InvoiceData,
    dt_definition: DocumentTypeDefinition | None,
) -> InvoiceData:
    if dt_definition is None:
        return data
    absent = {str(f).strip().lower() for f in (dt_definition.absent_fields or []) if str(f).strip()}
    if not absent:
        return data

    updates: dict[str, object] = {}
    scalar_map = {
        "vendor": "vendor",
        "abn": "abn",
        "invoice_no": "invoice_no",
        "invoice_date": "invoice_date",
        "due_date": "due_date",
        "po_reference": "po_reference",
        "subtotal": "subtotal",
        "gst": "gst",
        "total": "total",
        "cost_centre": "cost_centre",
        "billing_address": "billing_address",
        "bank_bsb": "bank_bsb",
        "bank_account": "bank_account",
        "line_items": "line_items",
    }
    for key in absent:
        attr = scalar_map.get(key)
        if attr == "line_items":
            updates["line_items"] = []
        elif attr and hasattr(data, attr):
            updates[attr] = None

    extracted = dict(extracted_fields_from_parsed(data))
    for key in absent:
        extracted.pop(key, None)
    if extracted != extracted_fields_from_parsed(data):
        updates["extracted_fields"] = extracted

    if updates:
        return replace(data, **updates)
    return data


def _persist_auxiliary_fields(data: InvoiceData, local_raw: dict[str, Any]) -> InvoiceData:
    extracted = merge_extracted_field_maps(extracted_fields_from_parsed(data))
    if local_raw.get("grn_reference"):
        extracted["grn_reference"] = str(local_raw["grn_reference"])
    if local_raw.get("gstin"):
        extracted["gstin"] = str(local_raw["gstin"])
    raw_fields = dict(data.raw_fields or {})
    if local_raw.get("gstin"):
        raw_fields["gstin"] = local_raw["gstin"]
    if not extracted and not raw_fields.get("gstin"):
        return data
    return replace(
        data,
        extracted_fields=extracted or data.extracted_fields,
        raw_fields=raw_fields,
    )


def _configured_scalar_fill_fields(
    dt_definition: DocumentTypeDefinition | None,
) -> tuple[str, ...]:
    if dt_definition is None:
        return _SCALAR_FILL_FIELDS
    configured = _configured_key_set(dt_definition)
    allowed: list[str] = []
    for field_name in _SCALAR_FILL_FIELDS:
        if _field_configured(field_name, configured):
            allowed.append(field_name)
    return tuple(allowed)


def merge_extraction_sources(
    parsed: InvoiceData,
    ocr: OcrArtifact,
    *,
    dt_definition: DocumentTypeDefinition | None = None,
    di_data: InvoiceData | None = None,
) -> InvoiceData:
    """Merge LLM/DI/layout/regex into one InvoiceData with DT-aware cleanup."""
    text = (ocr.text or parsed.document_text or "").strip()
    merged = parsed
    configured_keys = _configured_key_set(dt_definition)
    if text and not (merged.document_text or "").strip():
        merged = replace(merged, document_text=text)

    payload = ocr.payload_json or {}
    di_from_payload = invoice_data_from_payload_fields(payload.get("invoice_fields"))
    di_candidate = di_data or di_from_payload
    if di_candidate is not None and (not configured_keys or configured_keys & _DI_MERGE_KEYS):
        merged = _merge_prefer_complete(merged, di_candidate)

    kv = dict(ocr.layout_kv or {})
    if text:
        kv_from_text = extract_key_value_fields(None, text)
        for key, value in kv_from_text.items():
            kv.setdefault(key, value)
    merged = _apply_layout_kv(merged, kv, configured=configured_keys)

    if text:
        local = parse_local_text(text)
        llm_bsb = merged.bank_bsb
        llm_account = merged.bank_account
        fill: dict[str, object] = {}
        for field_name in _configured_scalar_fill_fields(dt_definition):
            current = getattr(merged, field_name, None)
            fallback = getattr(local, field_name, None)
            if _scalar_empty(current) and not _scalar_empty(fallback):
                fill[field_name] = fallback
        merged_items = list(merged.line_items)
        merge_line_items = not configured_keys or "line_items" in configured_keys
        if merge_line_items:
            llm_items_trusted = has_trusted_line_items(merged_items)
            if not llm_items_trusted:
                if local.line_items:
                    merged_items = merge_line_item_lists(merged_items, local.line_items)
                payload_items = line_items_from_ocr_payload(dict(ocr.payload_json or {}))
                if payload_items:
                    merged_items = merge_line_item_lists(merged_items, payload_items)
            if text.strip() and merged_items and not llm_items_trusted:
                merged_items = enrich_line_items_from_text(merged_items, text)
            merged_items = sanitize_line_items(
                merged_items,
                ocr_text=text,
                extracted_fields=merged.extracted_fields,
                vendor=merged.vendor,
                invoice_no=merged.invoice_no,
                po_reference=merged.po_reference,
                so_reference=(merged.extracted_fields or {}).get("so_reference"),
                cost_centre=merged.cost_centre,
            )
            if merged_items != merged.line_items:
                fill["line_items"] = merged_items
        bank_bsb, bank_account = merge_bank_fields(
            llm_bsb=llm_bsb,
            llm_account=llm_account,
            regex_bsb=local.bank_bsb if _field_configured("bank_bsb", configured_keys) else None,
            regex_account=local.bank_account if _field_configured("bank_account", configured_keys) else None,
            ocr_text=text,
        )
        if bank_bsb != merged.bank_bsb:
            fill["bank_bsb"] = bank_bsb
        if bank_account != merged.bank_account:
            fill["bank_account"] = bank_account
        if fill:
            merged = replace(merged, **fill)
        merged = _persist_auxiliary_fields(merged, local.raw_fields)

    permit_fields = (
        extract_permit_fields_from_text(text)
        if text and configured_keys & {"permit_no", "consignment_ref"}
        else {}
    )
    dt_custom_keys: list[str] = []
    if dt_definition is not None:
        dt_custom_keys = non_canonical_extraction_keys(list(configured_keys))
    ocr_custom = extract_custom_fields_from_text(text, dt_custom_keys) if text else {}
    merged_extracted = merge_extracted_field_maps(
        extracted_fields_from_parsed(merged),
        permit_fields,
        ocr_custom,
    )
    if merged_extracted:
        merged = replace(merged, extracted_fields=merged_extracted)
    elif not merged.extracted_fields and text:
        local = parse_local_text(text)
        custom = harvest_custom_fields_from_llm_raw(local.raw_fields)
        if custom:
            merged = replace(merged, extracted_fields=custom)

    merged = post_process_parsed_data(merged, text, dt_definition=dt_definition)
    merged = ground_invoice_scalars(merged, text)
    merged = _apply_absent_fields(merged, dt_definition)

    from app.services.extraction.party_field_service import sanitize_address

    if merged.billing_address:
        merged = replace(merged, billing_address=sanitize_address(merged.billing_address) or None)
    party_addr = (merged.extracted_fields or {}).get("buyer_address")
    if party_addr and not merged.billing_address:
        merged = replace(merged, billing_address=sanitize_address(party_addr) or None)

    return merged
